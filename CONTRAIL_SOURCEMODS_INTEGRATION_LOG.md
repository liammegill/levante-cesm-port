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
