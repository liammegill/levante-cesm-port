# Contrail-Cirrus SourceMods Integration Log

Covers integrating the Gettelman et al. (2021) contrail-cirrus SourceMods
into a working case, wiring up the converted GAIA aircraft-emission
inventory and MERRA2 nudging, and switching to the Specified-Dynamics
compset. Done on the `cam6_2_022` branch (case `levante_sd_022`), building
on the already-validated port covered by `LEVANTE_PORT_LOG.md` and
`CAM6_2_022_DELTA_LOG.md`.

Status at time of writing: build succeeds; the run reaches CAM's chemistry
initialization before failing on a genuine input-data content gap (§5).
Not yet a completed run.

---

## 1. SourceMods placement

The five modified files (`aircraft_emit.F90`, `ssatcontrail.F90`,
`tracer_data.F90`, `physpkg.F90`, `horizontal_interpolate.F90`) were copied
directly into the case's `SourceMods/src.cam/` directory. CIME picks these
up automatically at build time, replacing the corresponding stock files
for this case only.

## 2. `ac_factor` hardcoded path and line-length fix

`aircraft_emit_init` (in `aircraft_emit.F90`) reads 53 weekly scaling
factors from a hardcoded path on Andrew Gettelman's own NCAR home
directory (`/glade/u/home/andrew/cesm_ch/covid_air/ac_factor_2020all.dat`),
which cannot exist on Levante. Two issues needed fixing in the SourceMods
copy:

- The path itself, repointed to a file generated locally (see §3).
- The resulting `open(...)` line came to 133 characters — one over
  free-form Fortran's 132-character limit — and needed splitting using
  proper string-continuation syntax (`&` at the end of one line, `&` at
  the start of the next):
  ```fortran
  open(101,file='/work/bd1062/b309257/cam6-contrail-cirrus/inputdata/atm/cam/chem/ac_factor/&
       &ac_factor_2020all.dat',form='formatted')
  ```

## 3. Generating the `ac_factor` file: a 52-vs-53-week mismatch

`weekly_flight_fraction_2020all.nc` (from the paper's Zenodo record) has
52 weekly values. The Fortran code reads exactly 53
(`do m=1,53 read(101,*) ac_factor(m)`). Tracing `ssatcontrail.F90`'s
day-to-week-index formula for late December
(`(335+day-1)/7+1` under integer division) shows days 30–31 of December
genuinely index into slot 53 — 52 weeks × 7 days is 364, one or two days
short of a full year. Fix: generate a 53rd value by duplicating week 52's
value (the most defensible choice for the final day or two of the year,
absent any other information), then write all 53 values as plain
whitespace-separated numbers to a new file. The resulting sequence
(near 1.0 pre-COVID, dropping to ~0.33–0.35 during the March–April
lockdown weeks, recovering to ~0.87 by year end) matches the paper's own
qualitative description of the 2020 flight-reduction pattern.

## 4. Two genuine interface mismatches between Gettelman's files and this CAM tag

Since `physpkg.F90` in SourceMods is a *complete file replacement* (not a
patch), it carries along Gettelman's entire file exactly as it existed
when he made his edits — including any surrounding code he didn't touch.
Where the *stock* (untouched) CAM interfaces have since evolved, his
carried-along calls to them no longer match. Both mismatches were found by
diffing the stock `physpkg.F90` (still present, unmodified, in the main
CAM checkout) against the SourceMods copy — the principle applied
throughout: since Gettelman's files aren't version-tracked and the stock
CAM checkout is, fixes always adapt his files to the current stock
interfaces, never the reverse.

### 4.1 `microp_aero_init()` called with no arguments

Stock (current) interface, confirmed directly in
`components/cam/src/physics/cam/microp_aero.F90`:
```fortran
subroutine microp_aero_init(pbuf2d)
```
Gettelman's `physpkg.F90` calls it with zero arguments
(`call microp_aero_init()`). `pbuf2d` is already a valid local variable in
the enclosing subroutine (`phys_init`). Fix: add the argument at the call
site.

### 4.2 `phys_init` missing the `cam_in` argument entirely

The stock caller (`cam_comp.F90`, untouched, current) calls:
```fortran
call phys_init( phys_state, phys_tend, pbuf2d, cam_in, cam_out )
```
but Gettelman's `phys_init` signature only declares four arguments
(`phys_state, phys_tend, pbuf2d, cam_out`) — missing `cam_in` entirely.
Diffing stock vs. SourceMods `physpkg.F90` showed the surrounding stock
file has since gained an entire "cam_snapshot" diagnostic capability and a
"lunar_tides" module — both unrelated to contrails, confirming Gettelman's
baseline predates these additions — and, incidentally, the exact
declaration needed: `type(cam_in_t), intent(in) :: cam_in(begchunk:endchunk)`
(`cam_in_t` was already imported via an existing `use camsrfexch` line).
Fix: add `cam_in` to the signature (in the correct position, matching the
stock call) and add the matching declaration. No other changes were
needed — Gettelman's own code doesn't reference `cam_in`, so this is
purely a signature-matching fix, not a logic change.

**Both fixes were confirmed correct by a subsequent clean rebuild
succeeding** (`case.build --clean atm` between each fix, to force
correct dependency/module regeneration given `ssatcontrail.F90` is an
entirely new file with no prior build history for `make` to reason about).

## 5. New case: `levante_sd_022`, Specified Dynamics compset

Created as a separate case (not modifying `levante_port_test_022`), same
sandbox/build environment, using the CIME-defined `FSD` compset alias:
```
HIST_CAM60%SDYN_CLM50%SP_CICE%PRES_DOCN%DOM_MOSART_SGLC_SWAV
```
— identical to the validated test compset except `CAM60` → `CAM60%SDYN`.
SourceMods copied over from the `levante_port_test_022` case.

### 5.1 `%SDYN` defaults to 56 vertical levels, not the paper's 32

`config_component.xml` hardcodes the vertical level count by regex match
on the compset string:
```xml
<value compset="_CAM\d0%SDYN_CLM">-nlev 56</value>
```
This matches our exact compset regardless of preference, and produced a
runtime crash (`hycoef_read: ERROR: file lev does not match model. lev
(file, model): 32  56`) against our chosen 32-level initial-condition
file. Since the paper explicitly states "the standard 32 levels (to
3 hPa)," this default was overridden directly:
```bash
./xmlchange CAM_CONFIG_OPTS="-phys cam6 -offline_dyn -nlev 32"
./case.build --clean-all
```
(`-nlev` is a compile-time CAM configure option — CPP-defined dimension
parameters like `PLEV` are baked into compiled objects, so this genuinely
needs a full clean rebuild, not just a namelist change; CIME's own
`xmlchange` output correctly flagged this.) This strongly suggests the
paper's own case setup included an explicit `-nlev 32` override of its
own, since the plain `%SDYN` compset here does not default to it.

### 5.2 Initial condition (`ncdata`)

No default `ncdata` exists for `RUN_STARTDATE=2019-01-01` specifically
(CAM's namelist defaults only cover a fixed set of pre-built IC dates).
Used a generic, perpetual January-1st climatological IC instead
(`ic_ymd="101"` in `namelist_defaults_cam.xml`,
`atm/cam/inic/fv/cami-mam3_0000-01-01_1.9x2.5_L32_c150407.nc`), while
still setting the model's actual calendar date (`RUN_STARTDATE`) to the
real `2019-01-01` needed to align with the MERRA2 nudging files, SST
forcing, and any other date-dependent input. This is standard practice
for nudged runs — the atmospheric state gets pulled into agreement with
real meteorology within the nudging relaxation timescale regardless of
the (necessarily approximate) starting point.

### 5.3 Nudging namelist (`nudging_nl`)

Confirmed present in this CAM tag (`grep` against
`namelist_definition.xml`) before writing anything, given the paper's
described mechanism (a 24-hour *linear relaxation*, i.e. soft nudging) is
a different, separately-introduced CAM feature from the older "hard"
Specified-Dynamics state-replacement mechanism, and could plausibly have
postdated this specific tag.
```
Nudge_Model = .true.
Nudge_Path = '/work/bd1062/b309257/cam6-contrail-cirrus/inputdata/atm/cam/met/nudging/MERRA2_fv09_32L/'
Nudge_File_Template = '%y/MERRA2_fv09.cam2.i.%y-%m-%d-%s.nc'
Nudge_Times_Per_Day = 8
Model_Times_Per_Day = 48
Nudge_Beg_Year = 2019
Nudge_Beg_Month = 1
Nudge_Beg_Day = 1
Nudge_End_Year = 2019
Nudge_End_Month = 1
Nudge_End_Day = 31
Nudge_Uprof = 1
Nudge_Ucoef = 0.125
Nudge_Vprof = 1
Nudge_Vcoef = 0.125
Nudge_Tprof = 0
Nudge_Tcoef = 0.0
Nudge_Qprof = 0
Nudge_Qcoef = 0.0
Nudge_PSprof = 0
Nudge_PScoef = 0.0
```
Winds only (matching the paper's primary configuration; temperature
nudging is described as a separate sensitivity test). `Model_Times_Per_Day
= 48` matches the paper's stated 1800 s (30-minute) timestep
(86400/1800 = 48). The 0.125 coefficient is an approximation of the
paper's stated 24-hour relaxation timescale, extrapolated from a
documented reference pair (0.06 ↔ 50 h, 0.25 ↔ 12 h) — not independently
verified against CAM's own nudging-coefficient formula, and worth
revisiting if results look off.

### 5.4 Aircraft-emission namelist: a path-doubling bug

First attempt used the full absolute path for the filelist entry in
`aircraft_specifier`:
```
aircraft_specifier = 'ac_H2O->/work/.../aircraft_gaia2019/aircraft_gaia2019_filelist.txt', ...
aircraft_datapath = '/work/.../aircraft_gaia2019'
```
This produced a doubled, nonsensical path at runtime
(`.../aircraft_gaia2019//work/.../aircraft_gaia2019/....txt`) — confirmed
by re-reading `aircraft_emit_register`'s own logic
(`incr_filename(..., filenames_list=spc_flist(...), datapath=air_datapath)`),
which prepends `aircraft_datapath` onto whatever's given for the filelist
automatically. Fix: use just the bare filename in `aircraft_specifier`:
```
aircraft_specifier = 'ac_H2O->aircraft_gaia2019_filelist.txt',
                      'ac_SLANT_DIST->aircraft_gaia2019_filelist.txt'
aircraft_datapath = '/work/bd1062/b309257/cam6-contrail-cirrus/inputdata/atm/cam/chem/emis/aircraft_gaia2019'
```
This is a namelist-only fix — no rebuild needed, just
`./preview_namelists` + resubmit.

---

## 6. Still-open blocker: LBC file doesn't cover 2019, and the substitute lacks required species

With everything above fixed, the run advanced further but failed inside
chemistry initialization (`mo_flbc.F90`, via `chem_surfvals.F90`) reading
the lower-boundary-condition (LBC) file for long-lived species (CH4, N2O,
CFCs, etc.).

**First failure:** the default LBC file
(`LBC_1750-2015_CMIP6_GlobAnnAvg_c180926.nc`) only covers through 2015 —
`RUN_STARTDATE=2019-01-01` is genuinely outside its time axis
(`flbc_inti: time out of bounds`). This is exactly the SSP2-4.5
emissions-coverage gap flagged as an open item earlier in the port
(§12 of `LEVANTE_PORT_LOG.md`), now actually encountered.

**Second failure, after substituting a longer-coverage file:** the only
alternative `flbc_file` listed in this tag's `namelist_defaults_cam.xml`
is `LBC_1765-2100_1.9x2.5_CCMI_RCP60_za_RNOCStrend_c141002.nc` — an
RCP6.0 (not SSP2-4.5) scenario file, used as a pragmatic stand-in since it
was the only option covering 2019 and the immediate goal was validating
the technical pipeline. This produced repeated `NetCDF: Variable not
found` errors in `mo_flbc.F90` — the file is missing one or more chemical
species this specific chemistry configuration expects. Not yet
diagnosed: which species are actually required (need to check this
build's active chemistry mechanism/`chem_mech.in`, already copied to
`CaseDocs` for this case) versus which species the RCP6.0 file actually
provides (`ncdump -h` on the file itself).

This needs real investigation, not another quick substitution:
1. Identify the exact list of species this compset's chemistry
   configuration requires as LBC input.
2. Either find a properly SSP2-4.5-consistent LBC file with the full
   required species set (checking NCAR's input-data archives properly,
   the way MERRA2 and GAIA were sourced, rather than picking whatever
   `namelist_defaults_cam.xml` happens to list), or determine whether the
   missing species can be reasonably held fixed/omitted for this specific
   study (recall the paper itself only cares about aviation water vapor —
   it's plausible some of these species don't materially affect the
   contrail-relevant physics, but this needs checking, not assuming).

---

## 7. Updated still-open list (supersedes relevant items in §12 of `LEVANTE_PORT_LOG.md`)

1. **LBC species/scenario gap** (§6 above) — actively blocking a
   completed run, next priority.
2. Once resolved, the 5-timestep smoke test on `levante_sd_022` still
   needs to actually be run to completion and verified (restart files,
   clean exit) — not yet done, since the LBC failure has pre-empted every
   attempt so far.
3. The nudging coefficient (0.125) is an approximation, not verified
   against CAM's own formula for a true 24-hour timescale.
4. Only January 2019 MERRA2 data is in place; the full 2019–2020 range
   (§8 of `LEVANTE_PORT_LOG.md`) is still needed for real experiment runs.
5. The three-way scenario comparison (full emissions / COVID-scaled /
   zero aviation) and the ensemble-member setup (10/20 members per the
   paper) haven't been started — this log covers only getting a single
   configuration to build and (nearly) run.
6. `cam_snapshot`/`lunar_tides` (found via the stock-vs-SourceMods diff,
   §4.2) were deliberately not backported — they're unrelated to
   contrails and add complexity for no benefit here, but worth knowing
   they exist if a future need arises.

---

# Session 2: Resolving the SSP2-4.5 Blocker, Nudging Pivot, and Two Real Code Bugs

Picks up directly from §6/§7 above (the LBC species/scenario blocker). Ends with a
fully working `levante_nudge_022_f09` case: SourceMods, soft nudging against
MERRA2, aircraft emissions, and SSP2-4.5 forcing, all running together
successfully at f09 resolution. This section documents how each remaining
issue was actually resolved, since several turned out to be more subtle (or
more wide-ranging) than they first appeared.

## 8. A structural correction: hard vs. soft forcing, and dropping `%SDYN`

Before any of the SSP2-4.5 work, the case had been built on the `%SDYN`
compset modifier (`-offline_dyn`), which turned out to be the wrong tool
entirely for this study. `%SDYN` **replaces** CAM's own dynamical core
outright, reading meteorology directly from `metdata_nl`/`met_data_file` --
a "hard" mechanism with no relaxation timescale, since there's nothing to
relax when the state is simply overwritten every timestep.

The paper (both Gettelman et al. 2020 and 2021) is explicit that it uses a
**24-hour linear relaxation** -- meaningless terminology for hard
replacement, and only sensible for **soft nudging** (`nudging_nl`), where
CAM's own dynamical core runs completely normally and an additional
relaxation term is *added* to its own tendency, pulling gently toward
MERRA2 rather than replacing the state outright. This distinction matters
scientifically here specifically because the contrail scheme's premise is
that injected aircraft water vapor genuinely interacts with the model's own
humidity/temperature/cloud fields -- under hard forcing those fields could
be partially overwritten before the model's own physics response to the
injected water vapor has a chance to matter.

**Fix:** dropped `%SDYN` entirely. New case built on the same plain
`HIST_CAM60_CLM50%SP_CICE%PRES_DOCN%DOM_MOSART_SGLC_SWAV` compset already
validated in Section 1, with `nudging_nl` added via `user_nl_cam`. This also
meant the `-nlev 56` compset default (§5.1) never applies in the first
place -- plain CAM6 defaults to 32 levels already, matching the paper and
our chosen initial condition.

## 9. Grid resolution: 0.9x1.25 (f09), not f19

The properly-regridded, 32-vertical-level MERRA2 nudging product (NSF NCAR
GDEX dataset d313002) is **only available at 0.9x1.25 resolution** -- no
1.9x2.5 option exists for this specific, correctly-regridded dataset (only
the *other*, wrong dataset -- d313003, 72 levels, needing our own vertical
regridding -- offers multiple resolutions). Rather than take on that
regridding work, the case was switched to CIME's `f09_f09_mg17` grid
alias, which resolves to exactly 0.9x1.25 and required no new nudging data
at all -- it's arguably an improvement anyway, since ~1 deg is the paper's
actual stated target resolution. This did require re-fetching the full set
of f09-resolution equivalents of every standard input file already
fetched at f19 (topo, domain, SST, initial condition, CMIP6 emissions,
CLM surface data, etc.) -- all via the same targeted per-file `svn export`
approach as the original f19 fetch, no new gotchas there.

## 10. A genuine stack-overflow bug, found by isolating stock CAM

Switching to f09 immediately produced a segfault (signal 11) deep in
`mo_drydep.F90` (dry deposition velocity / land-use-fraction mapping),
happening across most MPI ranks simultaneously, with no clear Fortran
error message -- just a raw crash. Initially suspected as a bug in this
specific CAM routine's handling of f09's finer grid.

**Isolation test (the key step):** built a completely bare-bones, stock
(no SourceMods, no nudging, no aircraft emissions) f09 case. It crashed
identically, at the exact same routine and even the same MPI task number
-- conclusively ruling out anything in our own SourceMods, nudging, or
namelist additions.

**Root cause, confirmed with hard evidence:** `mo_drydep.F90` uses large
automatic (stack-allocated) local arrays --
`tmp_frac_lu(plon,n_land_type,plat)` and `tmp_soilw_3d(plon,12,plat)` --
sized by the model's own grid dimensions. At f09 (plon=288, plat=192)
these are roughly 4x larger than at f19, totalling ~11 MB combined --
comfortably exceeding Levante's default 8 MB (`ulimit -s` = 8192)
per-process stack limit. At f19 the same arrays total under 3 MB, safely
within the limit, which is exactly why this was never seen before
switching resolutions. A raw segfault (not a clean "subscript out of
bounds" message) even under `DEBUG=TRUE`/bounds-checking is itself a good
diagnostic signature of a stack-overflow rather than a genuine indexing
bug -- bounds checking only catches language-level array violations, not
running out of stack space for a correctly-indexed array.

**Fix:** added an explicit `resource_limits` block to the Levante entry in
`config_machines.xml`, setting the stack to unlimited:
```xml
<resource_limits>
  <resource name="RLIMIT_STACK">-1</resource>
</resource_limits>
```
This must go as a sibling *after* the closing `</environment_variables>`
tag, not nested inside it (an easy mistake -- the schema validator will
catch it immediately if placed wrong: `xmllint --noout --schema
config_machines.xsd config_machines.xml`). `case.setup` itself confirms
the fix is live at runtime: `Setting resource.RLIMIT_STACK to -1 from
(8388608, -1)`. Confirmed by rerunning the same stock isolation case,
which then completed cleanly end-to-end at full (1024-task) scale.

This patch has been added to `patches/cime.patch` on this branch and
should be re-synced to the `cam6_2_020` branch too, since the same
stack-size issue would equally affect any f09 (or higher-resolution) run
built from that setup -- not yet done as of this writing.

## 11. The SSP2-4.5 emissions/forcing gap, resolved properly (not just LBC)

§6 of Section 1 identified that the default LBC file only covers to 2015.
It turned out this same gap affects several *other*, entirely separate
input-file categories too, each needing its own fix -- discovered one at a
time via runtime crashes rather than all at once, which argues for
front-loading a full audit on any future setup at a new simulation year
(see §11.5 below).

### 11.1 Lower boundary condition (LBC) -- confirmed fixed
`LBC_2014-2500_CMIP6_SSP245_0p5degLat_GlobAnnAvg_c190301.nc` (as already
covered in Section 1 §6-7) -- carried over unchanged into this case.

### 11.2 Surface/vertical aerosol and reactive-species emissions
The default `CMIP6_emissions_1750_2015` directory's ~23
anthropogenic/biomass-burning species-sector files (SO2, DMS, bc_a4,
pom_a4, so4_a1/a2, num_a1/a2/a4, SOAGx1.5, across anthro/bb/anthro-ene/
anthro-ag-ship/anthro-res sectors) were swapped for their
`emissions_ssp245/` equivalents -- confirmed via direct inspection (not
assumption) to be genuinely bit-identical to the historical data through
2015, concatenated with the SSP2-4.5 projection through 2101 (verified via
the SSP245 file's own embedded processing-history attribute, which
explicitly names the historical file it was built from). Same units
(`molecules/cm2/s`), same variable-naming convention (`emiss_bb` etc.).

Two further species (`num_pom_a4`, `pom_a4`) required a **substring-match
bug fix** in the automated old-file-to-new-file mapping script: matching
`pom_a4_anthro_surface` as a plain substring incorrectly matched inside
`num_pom_a4_anthro_surface` (a different species). Fixed by requiring the
match to start immediately after the known SSP245 filename prefix, not
just appear anywhere in the string.

### 11.3 Volcanic (`contvolcano`) and biogenic (`SOAG`) sources -- a
### two-part correction

Initially, both categories were lumped together and simply dropped
(`Nudge_Model`-style pragmatic simplification), on the assumption that
"natural, not scenario-dependent" implied "doesn't need extending." This
was **checked directly and found to be half wrong**:

- **Volcanic (`contvolcano`) files were never actually broken.** Direct
  inspection of the file's own `date` variable showed real coverage of
  **year 850 to year 5000** (`emissions-cmip6_*_contvolcano_vertical_
  850-5000_*.nc` -- the "850-5000" in the filename is literal, not a typo
  or a different numbering convention). This is a deliberately sparse
  (84 entries across 4150 years), long-term reference dataset representing
  roughly-constant background degassing, comfortably covering 2019 as-is.
  **These 5 entries were restored to their original, untouched files** --
  they never needed touching in the first place, and the earlier "drop"
  decision was a mistake caught by verifying rather than assuming.
- **Biogenic (`SOAGx1.5_biogenic_surface`) genuinely is capped at 2015**
  (confirmed: `date` variable spans 1750-01-16 to 2015-12-16 exactly,
  3192 monthly entries). No SSP245-consistent extended replacement was
  found after checking the `emissions_ssp245/` directory, the dedicated
  `CMIP6_emissions_2000climo/` directory (which does have a biogenic file,
  but is scoped to `scam="1"`/`camiop="1"` single-column-model test cases
  per its own namelist-defaults tagging, not general global runs -- trying
  it anyway reproduced the same time-bounds crash), and confirming CAM's
  dynamic MEGAN biogenic-VOC scheme (`megan_emis_nl`) exists in this CAM
  tag but isn't active in our chemistry configuration (would need a
  broader mechanism change, not a quick fix). **Decision, made explicitly
  with the user: drop this one entry** (remove from `srf_emis_specifier`
  entirely) as a deliberate, documented simplification -- a minor
  background SOA precursor source, not central to the aviation
  water-vapor question this study is about. Worth a proper search for
  what NCAR's own published CESM2 SSP scenario runs actually did here,
  before any final production run.

### 11.4 Stratospheric ozone, halons, and CH4-oxidation water vapor
Three more files, found only via runtime crashes (not the original file
audit -- see §11.5), all following the identical pattern (default file
capped at 2015, genuine SSP2-4.5-consistent replacement existing in the
same source directory):
- `prescribed_ozone_file`/`prescribed_strataero_file` (same file used for
  both): swapped `ozone_strataero_WACCM_L70_zm5day_18500101-20150103_
  CMIP6ensAvg_c180923.nc` (capped 2015-01-03) for
  `ozone_strataero_WACCM_L70_zm5day_18500101-21010201_CMIP6histEnsAvg_
  SSP245_c190403.nc` (confirmed extends to 2101-02-01).
- `tracer_cnst_file` (halons): swapped
  `tracer_cnst_halons_3D_L70_1849-2015_CMIP6ensAvg_c180927.nc` (capped
  2015-12-16) for `tracer_cnst_halons_3D_L70_1849-2101_CMIP6ensAvg_
  SSP2-4.5_c190403.nc` (confirmed extends to 2101-12-16).
- `H2OemissionCH4oxidationx2` (an `ext_frc_specifier` entry, stratospheric
  water vapor from methane oxidation): swapped the `.../elev/
  H2OemissionCH4oxidationx2_3D_L70_1849-2015_CMIP6ensAvg_c180927.nc`
  (capped 2015-12-16) for `.../elev/H2OemissionCH4oxidationx2_3D_L70_
  1849-2101_CMIP6ensAvg_SSP2-4.5_c190403.nc` (confirmed extends to
  2101-12-16).

### 11.5 Lesson: the split datapath+filename convention breaks naive audits
A comprehensive script-based audit of every file path in `atm_in` (53
unique full-path entries, checked programmatically via `netCDF4` for each
one's actual `date`/`time` coverage against 2019) was run partway through
this process and was genuinely useful -- but **initially missed
`tracer_cnst_file`, `prescribed_ozone_file`, and `prescribed_strataero_
file` entirely**, because these variables store only a **bare filename**,
with the directory given separately via a companion `*_datapath`
variable (the same convention our own `aircraft_specifier`/
`aircraft_datapath` uses) -- a search for full `/work/...` paths simply
never matches these. Any future audit of this kind should explicitly also
`grep -i "_datapath\s*=" atm_in` first, and reconstruct the corresponding
bare-filename entries' full paths before checking coverage -- checking
full-path-style entries alone is not sufficient. (`_filelist`-style
entries are a third possible convention, used by `aircraft_specifier` and
supported by `tracer_cnst_filelist` too, though empty/unused in this
particular case.)

Static/climatological files correctly need no date-coverage check at all:
anything with no `time` dimension, anything with a `time` dimension but no
`time` coordinate *variable* (the standard convention for a repeating
12-month climatology, e.g. `season_wes.nc`, `clim_soilw.nc`,
`regrid_vegetation.nc`), and the initial condition (`ncdata`) file itself,
which is read once as a starting snapshot and never needs ongoing
coverage regardless of its own internal date stamp.

## 12. Two genuine code bugs found and fixed in `tracer_data.F90`/`aircraft_emit.F90`

With every input file now covering 2019, the run advanced much further but
hit two more issues, both **inside the aircraft-emission SourceMods
themselves** (not the input data) -- both confirmed as genuine bugs (or at
least assumptions that don't generalize), not further data problems.

### 12.1 `aircraft_emit.F90`: `data_cycle_yr` hardcoded to 0

`aircraft_emit_init` calls `trcdata_init(..., rmv_file, 0, 0, 0, air_type)`
-- the first `0` is `data_cycle_yr`. Since `air_type = 'CYCLICAL_LIST'`,
this value flows into `file%cyc_yr`, which `get_model_time` uses to
compute the internal comparison time against the file's own data times
(via `set_time_float_from_date`). With `cyc_yr=0`, the code computed the
comparison using "year 0" instead of the actual simulated year (2019),
producing a nonsensical negative time value and a hard crash
(`find_times: all(all_data_times(:) > time)`) -- our file's single
time entry was (correctly) tagged for 2019, but being compared against a
"year 0" reference.

**Fix applied (flagged as a known, temporary simplification --
see §14 below):** changed the hardcoded `0` to `2019` directly in the
SourceMods copy, with a `TODO` comment left in place. **Not** a
permanent fix -- see the follow-up item.

### 12.2 `tracer_data.F90`: `CYCLICAL_LIST` incorrectly rejected by validation

Setting `data_cycle_yr` immediately hit a second, separate problem: a
validation check --
```fortran
if ( (.not.file%cyclical) .and. (data_cycle_yr>0._r8) ) then
   call endrun('trcdata_init: Cannot specify data_cycle_yr if data type is not CYCLICAL')
endif
```
-- only exempts `'CYCLICAL'` type, rejecting `'CYCLICAL_LIST'` outright.
But the code's own *usage* of `cyc_yr`, just a few lines further down, is
guarded by `if (file%cyclical .or. file%cyclical_list)` -- treating both
types identically. This is a genuine inconsistency in stock CAM's own
validation logic (this file, `tracer_data.F90`, is one of Gettelman's five
full-file-replacement SourceMods copies, but this specific check appears
to be untouched, carried-along stock code, not something he modified) --
the validation was simply never extended to match the later usage when
`CYCLICAL_LIST` support was presumably added.

**Fix:** extended the check to also exempt `cyclical_list`:
```fortran
if ( (.not.file%cyclical) .and. (.not.file%cyclical_list) .and. (data_cycle_yr>0._r8) ) then
   call endrun('trcdata_init: Cannot specify data_cycle_yr if data type is not CYCLICAL or CYCLICAL_LIST')
endif
```

With both fixes in place, `levante_nudge_022_f09` completed a full
5-timestep run cleanly (`case.run` + `case.st_archive`, both `COMPLETED`
exit `0:0`, full restart-file set present for every component at
`2019-01-01-09000`) -- the first genuinely complete, working run of the
integrated setup (SourceMods + soft nudging + aircraft emissions + SSP2-4.5
forcing, at f09).

## 13. The 1.88 traffic-growth multiplier removed from `ssatcontrail.F90`

Flagged as a known issue back in the original port log (§ "Key physics
facts about the contrail scheme" in the summary) but not actually acted on
until now: `ssatcontrail.F90` applied a hardcoded `*1.88_r8` factor to
both `ac_H2O` and `ac_SLANT_DIST`, representing Gettelman's own
2006-to-2020 air-traffic growth assumption for his original 2006-baseline
inventory. Since the GAIA 2019 inventory already represents present-day
(2019) traffic levels for both quantities, this factor would have
double-counted growth, inflating the water-vapor forcing by 88%. Removed
from both lines, retaining only the `curr_factor` (weekly COVID scaling)
multiplication:
```fortran
ac_H2O = ac_H2O*curr_factor  ! 1.88 (2006->2020 traffic growth) removed: GAIA 2019 inventory is already present-day
ac_SLANT_DIST = ac_SLANT_DIST*curr_factor  ! 1.88 removed, same reason as ac_H2O above
```

## 14. Still-open items (supersedes the equivalent list in Section 1, §7)

1. **`aircraft_cycle_yr` should be a namelist variable, not a hardcoded
   `2019` in the SourceMods source.** The clean fix: add a new namelist
   entry (e.g. `aircraft_cycle_yr`) read in `aircraft_emit_readnl`
   following the exact same pattern already used there for
   `aircraft_datapath`/`aircraft_specifier`, stored in a module-level
   variable, and passed into the `trcdata_init` call instead of the
   literal `2019`. As things stand, running a different simulation year
   requires editing and rebuilding the SourceMods copy again.
2. **Whether/how the `ac_factor` weekly-COVID-scaling array should apply
   to 2019 at all** hasn't been checked -- `weekly_flight_fraction_2020all.nc`
   is inherently a 2020-only dataset; how `ssatcontrail.F90`'s
   day-of-year-to-week-index logic behaves when the simulated date is in
   2019 (predating COVID) is unexamined.
3. **Biogenic emissions gap** (§11.3) -- deliberately dropped, not fixed.
   Worth a proper search for NCAR's own published CESM2/SSP-scenario
   convention here before any final production run, rather than leaving
   this out permanently.
4. **The f09 stack-size fix (§10) needs syncing to the `cam6_2_020`
   branch's `cime.patch`** -- not yet done. Any future f09 (or finer)
   case built from that branch would hit the identical stack overflow.
5. Everything already listed in Section 1's §7 that hasn't been
   superseded above: the full 2019-2020 MERRA2 transfer (only January
   2019 is in place), verifying the 0.125 nudging coefficient against
   CAM's actual formula for a true 24-hour timescale, the three-scenario
   (full/COVID/zero-aviation) ensemble setup itself, and the small
   temperature perturbation (~1e-10 K) needed per ensemble member.
6. Given the file-content assumptions that turned out wrong twice this
   session (contvolcano's real coverage, the split-datapath convention),
   **any future change of simulation year should start with the full
   programmatic file-coverage audit** (§11.5), not incremental
   crash-driven discovery -- it's slower up front but would have caught
   at least 3 of the 5 fixes in §11 in one pass rather than five separate
   rounds of build-submit-diagnose.
