# Levante CESM2/CAM6.2 Port Log — Gettelman et al. (2021) Replication

**Date:** 2026-07-27
**User:** Liam Megill (liam.megill@dlr.de)
**Machine:** DKRZ Levante, account `bd1062` / user `b309257`
**Goal:** Build a working CESM2/CAM6.2 executable on Levante, using the exact CAM tag (`cam6_2_020`) verified against the Gettelman et al. (2021) COVID-contrail paper's Zenodo dataset, as groundwork before the colleague's SAF/H2 contrail-cirrus extension work arrives.

This document is a self-contained account of everything done to get from zero to a successful `case.build`. It supersedes the parts of the original `HANDOFF.md` covering machine porting and build mechanics — read this first for anything Levante/build-related; the original handoff is still the reference for the science background, CAM source review, and missing-input-data questions.

---

## 1. Final working configuration (the "answer key")

If you just want to know what actually works, here it is. Sections 2+ explain how we got here and why each piece is necessary.

- **Top-level checkout:** cloned from `https://github.com/ESCOMP/CESM.git`, checked out at tag **`release-cesm2.1.3`**.
- **CIME version:** the default `cime5.6.32` pulled in by `release-cesm2.1.3` does **not** work — it's missing a function (`get_standard_makefile_args`) that CAM's build script needs. Fixed by overriding the top-level `Externals.cfg`'s `[cime]` entry to tag **`cime5.8.16`** instead (this is also the version CAM's *own* internal `Externals.cfg` recommends).
- **CAM tag:** `Externals.cfg`'s `[cam]` entry overridden to **`cam6_2_020`** (verified via the Gettelman et al. 2021 Zenodo record, see original `HANDOFF.md` §2).
- **All other externals** (CLM, CICE, MOSART, CISM, etc.): whatever `release-cesm2.1.3` pins by default — untouched.
- **Compset:** `HIST_CAM60_CLM50%SP_CICE%PRES_DOCN%DOM_MOSART_SGLC_SWAV` (explicit longname, **not** the `FHIST` alias — see §5.3 for why).
- **Grid:** `f19_f19_mg17` (~2°, for cheap validation; move to `f09`-class ~1° for the actual Gettelman-matching resolution later).
- **Compiler/module stack:**
  ```
  python3/2023.01-gcc-11.2.0
  intel-oneapi-compilers/2022.0.1-gcc-11.2.0
  intel-oneapi-mkl/2022.0.1-gcc-11.2.0
  openmpi/4.1.2-intel-2021.5.0
  netcdf-c/4.8.1-openmpi-4.1.2-intel-2021.5.0
  netcdf-fortran/4.5.3-openmpi-4.1.2-intel-2021.5.0
  parallel-netcdf/1.12.2-openmpi-4.1.2-intel-2021.5.0
  esmf/8.2.0-intel-2021.5.0
  ```
  **Important:** do *not* use `intel-oneapi-mpi` — despite the name, its bundled `mpicc` wraps plain GCC, not `icc`, on this system. Use the real Intel-compiled OpenMPI (`openmpi/4.1.2-intel-2021.5.0`) instead, which is what our `MPILIBS=openmpi` setting expects.
- **Perl for CLM's namelist step:** system `/usr/bin/perl` (5.26.3) does **not** have `XML::LibXML`. Fixed via a dedicated conda environment at `/work/bd1062/b309257/conda_envs/cesm-perl526` (Perl 5.26.2 + `perl-xml-libxml` from bioconda), wired in via a `PERL5LIB` **environment variable** in the machine config — deliberately *not* via `PATH`/conda-activation, to avoid conda's own `mpicc` shadowing the real Intel/OpenMPI one.
- **Directory layout (per DKRZ's storage tiers):**
  - Code checkout: `~/my_cesm_sandbox` (HOME — backed up, holds `SourceMods` and case dirs)
  - Input data / long-term output: `/work/bd1062/b309257/cam6-contrail-cirrus/` (WORK — large, not backed up, persists)
  - Active run directories: `/scratch/b/b309257/<casename>` (SCRATCH — 14-day auto-purge, never leave finished results here)

---

## 2. The core surprise: two different CESM/CIME version mismatches

Everything else in this log traces back to one root cause worth understanding up front.

`cam6_2_020` is not a tag that lines up with any official CESM release — it's an intermediate CAM development snapshot from April 2020, sitting chronologically between the CAM tags pinned by `release-cesm2.1.2`/`release-cesm2.1.3` (`cam_cesm2_1_rel_41`, Jan 2020) and `release-cesm2.2.0` (`cam_cesm2_2_rel_02`, later in 2020). We confirmed this by comparing commit dates directly in the CAM submodule's own git history — no top-level CESM release tag pins `cam6_2_020` exactly.

This caused two distinct problems:

1. **CIME API mismatch:** `release-cesm2.1.3`'s default CIME (`cime5.6.32`) doesn't have the `get_standard_makefile_args` function CAM's `buildlib` script imports. This function *does* exist in `cime5.8.16` — which happens to be exactly what CAM's own internal `Externals.cfg` (a separate file, used only when CAM is checked out standalone) already recommends. So: keep the CESM2.1.3-era CLM/CICE/MOSART/CISM, but override just the top-level CIME external to `cime5.8.16`.

2. **CIME driver-interface mismatch:** even with the right CIME, CLM's tagged source (from CESM2.1.3) calls a data-assimilation-resume function (`seq_infodata_GetData(..., lnd_resume=...)`) that doesn't exist in `cime5.8.16`'s `seq_infodata_mod` at all — a genuine feature-level gap, not a naming issue. Fixed by stubbing out the one subroutine that used it (see §6.6) since DA-resume is irrelevant to this project.

**Takeaway for later:** when the colleague's actual setup arrives, the first thing worth checking is exactly which CIME tag *he's* using — if it's neither `cime5.6.32` nor `cime5.8.16`, expect a fresh round of similar version-skew surprises.

---

## 3. Machine port: `config_machines.xml`

This CESM2.1.3-era CIME (both `cime5.6.32` initially, then `cime5.8.16` after the swap) uses a **monolithic** `config_machines.xml` file at `cime/config/cesm/machines/config_machines.xml` — no per-machine subdirectory fragments (that's a *later* CIME convention we hit when we briefly, mistakenly, tried building against a CESM3-alpha checkout early on — irrelevant to the final setup, but explains some early false starts).

Final Levante `<machine>` block (element order matters — this schema uses `xs:sequence`, verified against `cime/config/xml_schemas/config_machines.xsd`):

```xml
<machine MACH="levante">
  <DESC>DKRZ Levante, 2x AMD EPYC Milan (128 cores/node, SMT2=256), OS is Linux, batch system is Slurm</DESC>
  <NODENAME_REGEX>^levante</NODENAME_REGEX>
  <OS>LINUX</OS>
  <COMPILERS>intel,gnu</COMPILERS>
  <MPILIBS>openmpi</MPILIBS>
  <PROJECT>bd1062</PROJECT>
  <CIME_OUTPUT_ROOT>/scratch/b/$ENV{USER}</CIME_OUTPUT_ROOT>
  <DIN_LOC_ROOT>/work/bd1062/b309257/cam6-contrail-cirrus/inputdata</DIN_LOC_ROOT>
  <DIN_LOC_ROOT_CLMFORC>/work/bd1062/b309257/cam6-contrail-cirrus/inputdata/atm/datm7</DIN_LOC_ROOT_CLMFORC>
  <DOUT_S_ROOT>/work/bd1062/b309257/cam6-contrail-cirrus/archive/$CASE</DOUT_S_ROOT>
  <BASELINE_ROOT>/work/bd1062/b309257/cam6-contrail-cirrus/cesm_baselines</BASELINE_ROOT>
  <CCSM_CPRNC>UNSET</CCSM_CPRNC>
  <GMAKE_J>8</GMAKE_J>
  <BATCH_SYSTEM>slurm</BATCH_SYSTEM>
  <SUPPORTED_BY>liam.megill -at- dlr.de</SUPPORTED_BY>
  <MAX_TASKS_PER_NODE>256</MAX_TASKS_PER_NODE>
  <MAX_MPITASKS_PER_NODE>128</MAX_MPITASKS_PER_NODE>
  <PROJECT_REQUIRED>TRUE</PROJECT_REQUIRED>
  <mpirun mpilib="default">
    <executable>srun</executable>
    <arguments>
      <arg name="label"> --label</arg>
      <arg name="num_tasks"> -n {{ total_tasks }}</arg>
    </arguments>
  </mpirun>
  <module_system type="module">
    <init_path lang="perl">/usr/share/Modules/init/perl.pm</init_path>
    <init_path lang="python">/usr/share/Modules/init/python.py</init_path>
    <init_path lang="csh">/usr/share/Modules/init/csh</init_path>
    <init_path lang="sh">/usr/share/Modules/init/sh</init_path>
    <cmd_path lang="perl">/usr/bin/modulecmd perl</cmd_path>
    <cmd_path lang="python">/usr/bin/modulecmd python</cmd_path>
    <cmd_path lang="sh">module</cmd_path>
    <cmd_path lang="csh">module</cmd_path>
    <modules>
      <command name="load">python3/2023.01-gcc-11.2.0</command>
      <command name="load">intel-oneapi-compilers/2022.0.1-gcc-11.2.0</command>
      <command name="load">intel-oneapi-mkl/2022.0.1-gcc-11.2.0</command>
      <command name="load">openmpi/4.1.2-intel-2021.5.0</command>
      <command name="load">netcdf-c/4.8.1-openmpi-4.1.2-intel-2021.5.0</command>
      <command name="load">netcdf-fortran/4.5.3-openmpi-4.1.2-intel-2021.5.0</command>
      <command name="load">parallel-netcdf/1.12.2-openmpi-4.1.2-intel-2021.5.0</command>
      <command name="load">esmf/8.2.0-intel-2021.5.0</command>
    </modules>
  </module_system>
  <environment_variables>
    <env name="PERL5LIB">/work/bd1062/b309257/conda_envs/cesm-perl526/lib/site_perl/5.26.2/x86_64-linux-thread-multi:/work/bd1062/b309257/conda_envs/cesm-perl526/lib/site_perl/5.26.2</env>
  </environment_variables>
</machine>
```

Key decisions embedded here:
- **`OS` is `LINUX` (not `CNL`)** — `CNL` is Cray-specific; we adapted from a Perlmutter template initially and had to correct this.
- **`module_system type="module"`**, not Lmod — Levante uses classic Tcl-based Environment Modules (`$MODULESHOME=/usr/share/Modules`), confirmed via `echo $MODULESHOME`. A first draft copied Perlmutter's Lmod-based paths (`libexec/lmod`) verbatim, which don't exist here.
- **`NODENAME_REGEX` is per-machine** in this CIME version's schema (not a centralized top-level block — that's a different, later-CIME convention). It's optional anyway; `create_newcase --machine levante` always sets the machine explicitly.
- **`PROJECT_REQUIRED` must come after `mpirun`** in the v2.0 schema's element sequence (schema order: ... `MAX_MPITASKS_PER_NODE`, `COSTPES_PER_NODE`, `PROJECT_REQUIRED`, `mpirun`, `module_system`, `environment_variables`, `resource_limits`).

## 4. Machine port: `config_batch.xml`

Same monolithic-file convention, at `cime/config/cesm/machines/config_batch.xml`. Uses `<arg flag="..." name="..."/>` syntax for `submit_args` (a different, older convention than the `<argument>` tag style seen in some newer-CIME templates):

```xml
<batch_system MACH="levante" type="slurm">
  <batch_submit>sbatch</batch_submit>
  <submit_args>
    <arg flag="--time" name="$JOB_WALLCLOCK_TIME"/>
    <arg flag="-p" name="$JOB_QUEUE"/>
    <arg flag="--account" name="$PROJECT"/>
  </submit_args>
  <queues>
    <queue walltimemin="0" walltimemax="08:00:00" nodemin="1" nodemax="500" default="true">compute</queue>
    <queue walltimemin="0" walltimemax="12:00:00" nodemin="1" nodemax="30">interactive</queue>
    <queue walltimemin="0" walltimemax="7-00:00:00" nodemin="1" nodemax="20">shared</queue>
  </queues>
</batch_system>
```

Note: `-p` is SLURM's real partition flag; some other machines' templates use `-q` as a site-specific alias, which would be wrong here.

`nodemax` values are placeholders, not confirmed against real DKRZ per-job limits — worth checking with DKRZ support or docs before relying on them for a large production run.

## 5. Machine port: `config_compilers.xml`

Same monolithic-file convention, at `cime/config/cesm/machines/config_compilers.xml`. This schema uses `xs:choice` internally (not a strict `xs:sequence`), so element order doesn't matter here, unlike the two files above.

```xml
<compiler MACH="levante">
  <SCC>icc</SCC>
  <SCXX>icpc</SCXX>
  <SFC>ifort</SFC>
  <SUPPORTS_CXX>TRUE</SUPPORTS_CXX>
  <NETCDF_C_PATH>/sw/spack-levante/netcdf-c-4.8.1-2k3cmu</NETCDF_C_PATH>
  <NETCDF_FORTRAN_PATH>/sw/spack-levante/netcdf-fortran-4.5.3-k6xq5g</NETCDF_FORTRAN_PATH>
</compiler>
```

Why `SCC`/`SCXX`/`SFC`/`SUPPORTS_CXX` are needed even though a generic `<compiler COMPILER="intel">` block already sets them: CIME's macro-merging appears to give machine-specific (`MACH=`) blocks precedence in a way that does *not* fall through to compiler-generic (`COMPILER=`) values for variables the machine block leaves unset. Empirically, CLM's build failed with "Fatal attempt to include C++ code on a compiler/machine combo that has not been set up to support C++" until these were added directly to the `MACH="levante"` block, even though the generic Intel block already had them. Rather than fully reverse-engineer CIME's exact precedence rules, we just duplicated the settings locally — safe and it worked.

`NETCDF_C_PATH`/`NETCDF_FORTRAN_PATH` (split form) were used instead of a combined `NETCDF_PATH`, since Levante's `netcdf-c` and `netcdf-fortran` are genuinely separate Spack install prefixes (unlike some HPC sites with one combined NetCDF module/directory).

### 5.1 A note on `Macros.make` regeneration

`case.setup` only regenerates `Macros.make` if the file doesn't already exist — editing `config_compilers.xml` (or `config_machines.xml`) after a case has been set up does **not** automatically propagate. If you change either file for an existing case, you must:
```bash
rm Macros.make Macros.cmake
./case.setup
```
before rebuilding. We hit this exact trap twice during this session.

### 5.2 A note on the `Macros.<machine-name>` file

Some component build scripts from this CESM2.1.3 era (CLM, notably) construct their own path to a machine-specific macros file (e.g. `Macros.levante`) rather than using the generic `Macros.make` that `case.setup` actually generates. If you hit an error like `NETCDF not found` where `Macros.make` clearly *does* define the right variables, check whether the failing component's `buildlib` script is looking for `Macros.<mach>` instead — if so, `ln -s Macros.make Macros.<mach>` fixes it (though in our case the deeper CASEROOT bug below turned out to matter more).

### 5.3 Why we don't use the `FHIST` alias

With `cime5.8.16`, the `FHIST` compset alias resolves to `..._MOSART_CISM2%NOEVOLVE_SWAV_SIAC_SESP` by default — i.e. it pulls in the full CISM ice-sheet component (even in ice-evolution-off mode) and an IAC stub. CISM's build uses CMake with its own, differently-wired compiler/NetCDF detection that we could not get working cleanly with the Intel toolchain (its CMake invocation silently defaulted `FC` to empty, causing it to fall back to system `gfortran`/`f95`, which then failed to find MPI modules built for Intel). Since CISM (ice-sheet dynamics) is irrelevant to the Gettelman et al. contrail-cirrus science, we sidestepped it entirely by requesting the explicit compset longname with `SGLC` (stub glacier) instead of `CISM2%NOEVOLVE`:

```
HIST_CAM60_CLM50%SP_CICE%PRES_DOCN%DOM_MOSART_SGLC_SWAV
```

`create_newcase` auto-adds `SIAC`/`SESP` stub components regardless; this is expected and harmless.

---

## 6. Source-code and script patches applied

All patches are captured as git diffs in the accompanying backup repo (`~/levante_port_backup` on Levante) — `patches/cime.patch`, `patches/clm.patch`, `patches/cice.patch`, `patches/mosart.patch`, `patches/cism.patch`. This section explains *why* each one was needed.

### 6.1 `components/clm/cime_config/buildlib`, `components/cice/cime_config/buildlib`, `components/mosart/cime_config/buildlib`

These three component build scripts, as tagged in this checkout, hand-construct their `gmake` invocation as a literal string — and each one **omits `CASEROOT`** (and CLM's also omitted `CASETOOLS`) from that command line. Since `Tools/Makefile` does `include $(CASEROOT)/Macros.make`, a missing `CASEROOT` silently fails to find the macros file, leaving things like `NETCDF_C_PATH` undefined and producing a confusing downstream `NETCDF not found` error that looks environmental but isn't.

Rather than patch each missing variable individually (we found `CASEROOT` missing, then `CASETOOLS`, then indications more might be missing for CLM), we replaced the hand-rolled `cmd`/`run_cmd`/`expect` blocks with a call to CIME's own `CIME.buildlib.run_gmake()` helper, which internally calls `get_standard_makefile_args()` to supply every standard variable at once. This is more robust and is what "should" have been used originally.

**CLM** (`components/clm/cime_config/buildlib`) — replaced the `clm5_0` (non-`clm4_0`) branch:
```python
# before:
else:
    cmd = "%s complib -j %d MODEL=clm COMPLIB=%s -f %s MACFILE=%s " \
          % (gmake, gmake_j, complib, makefile, macfile )
    rc, out, err = run_cmd(cmd)
    ...

# after:
else:
    run_gmake(case, "clm", libroot, bldroot, libname="clm")
```
(also added `run_gmake` to the `from CIME.buildlib import parse_input` line)

**CICE** (`components/cice/cime_config/buildlib`):
```python
# replaced the cmd/run_cmd/expect block with:
run_gmake(case, "ice", libroot, bldroot, libname="ice", user_cppdefs=cice_cppdefs)
```

**MOSART** (`components/mosart/cime_config/buildlib`):
```python
# replaced the cmd/run_cmd/expect block with:
run_gmake(case, "rof", libroot, bldroot, libname="rof")
```

**Caveat worth knowing:** `run_gmake()`'s own implementation does *not* check the underlying command's return code (`_, out, _ = run_cmd(cmd, combine_output=True); print(out)` — no `expect(rc==0, ...)`). This means a genuine compile failure inside one of these components will be silently swallowed and reported as "built in X seconds" success, only surfacing much later when the final link step can't find the missing `.a` library. This bit us directly (see §6.4/§6.5) — if a build "succeeds" suspiciously fast or the final link complains a library file doesn't exist anywhere, check the individual component's `.bldlog` file by hand for real compiler errors, don't trust the "built in X seconds" line.

### 6.2 `components/cism/cime_config/buildlib` (Perl)

Same missing-`CASEROOT` bug, in Perl this time. Two `$sysmod` command strings needed `CASEROOT=$CASEROOT` appended:
```perl
# line ~115 (cmake configure/build step):
my $sysmod = "... -f $CASETOOLS/Makefile EXEROOT=$EXEROOT CASEROOT=$CASEROOT";

# line ~132 (cesm-specific complib step):
my $sysmod = "... GLC_DIR=$glc_dir -f $CASETOOLS/Makefile CASEROOT=$CASEROOT";
```
This fix became moot once we switched to the `SGLC` compset (§5.3) and stopped building CISM at all, but is documented here in case CISM is ever re-enabled.

### 6.3 `components/clm/src/biogeophys/UrbanTimeVarType.F90`

Line ~128 declared `character(SHR_KIND_CL)` — the fully-qualified name — but this file only imports the kind under the local alias `CL` (`use shr_kind_mod, only : CL => shr_kind_CL`), not the bare name. Fixed:
```fortran
! before:
character(SHR_KIND_CL)  :: fldList
! after:
character(len=CL)       :: fldList
```

### 6.4 `components/clm/src/biogeochem/SatellitePhenologyMod.F90` and `components/clm/src/biogeophys/SoilMoistureStreamMod.F90`

Same class of bug, different kind (`SHR_KIND_CXX`, a genuine distinct 4096-char kind constant, not a typo for `CL`). Neither file imported it at all. Fixed by adding the import and using the alias, in both files:
```fortran
! added:
use shr_kind_mod    , only : CXX => shr_kind_CXX
! changed:
character(SHR_KIND_CXX)    :: fldList   →   character(len=CXX)        :: fldList
```

### 6.5 `components/cice/src/source/ice_atmo.F90` and `components/cice/src/drivers/cesm/ice_prescribed_mod.F90`

Same bug pattern again, but in CICE's own kind system (`ice_kinds_mod`, not `shr_kind_mod` — CICE doesn't use CESM's shared kind module in these files at all). The names `SHR_KIND_R8`/`SHR_KIND_IN` used were simply never valid in this context; the correct local names (already used elsewhere in the same files) are `dbl_kind`/`int_kind`.
```fortran
! ice_atmo.F90:
ustar_prev = 2.0_SHR_KIND_R8 * ustar   →   ustar_prev = 2.0_dbl_kind * ustar

! ice_prescribed_mod.F90:
integer(SHR_KIND_IN),parameter :: nFilesMaximum = 400   →   integer(kind=int_kind),parameter :: nFilesMaximum = 400
```

**Note:** two more files matched the same `SHR_KIND_*`-misuse grep pattern (`components/clm/src/unit_test_stubs/csm_share/shr_mpi_mod_stub.F90`, `components/cice/src/csm_share/shr_orb_mod.F90`) but were *not* touched, since neither actually failed during our build (the CICE one has the `use shr_kind_mod` line already commented out — looks like unused/dead code for our compset; the CLM one is a unit-test stub not exercised by a normal build). Worth re-checking only if a different compset/build path ever exercises them.

### 6.6 `components/clm/src/cpl/lnd_comp_mct.F90` — `lnd_handle_resume` stubbed out

This subroutine calls `seq_infodata_GetData(infodata, lnd_resume=lnd_resume)` — a genuine CIME driver-interface gap: `lnd_resume` doesn't exist anywhere in `cime5.8.16`'s `seq_infodata_mod.F90` (confirmed by grep — zero mentions of "resume" in that file at all). This is CLM's data-assimilation resume-signal handling, entirely unrelated to contrail-cirrus science and not needed for this project. Replaced the subroutine body with a no-op, keeping the signature intact so its two call sites (lines 262, 380 of the same file) still compile:
```fortran
subroutine lnd_handle_resume( infodata )
  !
  ! !DESCRIPTION:
  ! Handle resume signals for Data Assimilation (DA)
  ! NOTE: disabled -- lnd_resume is not available in this CIME driver version (cime5.8.16);
  ! not needed for this project (no data assimilation is used).
  !
  ! !USES:
  use seq_infodata_mod , only : seq_infodata_type
  implicit none
  ! !ARGUMENTS:
  type(seq_infodata_type), intent(IN) :: infodata     ! CESM driver level info data
  !---------------------------------------------------------------------------
end subroutine lnd_handle_resume
```

---

## 7. Environment / dependency setup (not source patches, but required)

### 7.1 `XML::LibXML` for Perl (needed by CLM's `build-namelist`)

CLM's `build-namelist` script (`#!/usr/bin/env perl` shebang) needs the `XML::LibXML` Perl module, which system Perl (5.26.3) doesn't have, and which we could not get CPAN (`cpanm`) to install correctly — every attempt reported "Successfully installed" while silently failing to actually copy files into place (a `make`/`pm_to_blib` staging bug we never fully root-caused, possibly a stale-timestamp/clock-skew artifact between filesystem mounts).

**Working fix:** installed via conda/bioconda instead, pinned to Perl 5.26 to match system Perl's ABI exactly (XS/compiled-extension compatibility requires matching major.minor Perl versions):
```bash
mamba create --prefix /work/bd1062/b309257/conda_envs/cesm-perl526 \
  -c bioconda -c conda-forge "perl=5.26" perl-xml-libxml -y
```
Then wired in via `PERL5LIB` (not `PATH`) in `config_machines.xml`'s `<environment_variables>` block (§3) — critically, **not** by activating the conda environment in the shell, since that would also put conda's own `mpicc` on `PATH`, shadowing the real Intel/OpenMPI one and reintroducing the exact GCC-vs-Intel flag mismatch described in §3's compiler note.

Two library paths were needed (arch-specific for the compiled `.so`, plus a pure-Perl path for a sub-dependency, `XML::SAX::Exception`):
```
/work/bd1062/b309257/conda_envs/cesm-perl526/lib/site_perl/5.26.2/x86_64-linux-thread-multi
/work/bd1062/b309257/conda_envs/cesm-perl526/lib/site_perl/5.26.2
```

A separate, non-version-pinned conda environment (`cesm-perl`, Perl 5.32) was created first and works fine standalone (`perl -MXML::LibXML` succeeds), but its Perl version doesn't match system Perl's ABI, so it's only useful if you activate its own `perl` binary directly (which we avoided for the `mpicc`-shadowing reason above). It's harmless to leave in place at `/work/bd1062/b309257/conda_envs/cesm-perl` but isn't used by the final machine config.

### 7.2 `svn` and `git` modules

Needed at various points (Subversion for `chem_proc`/`carma` externals checkout; `git` for CESM's own externals and for the build's provenance-recording step). Both are Spack modules (`module load subversion`, `module load git/2.43.7-gcc-11.2.0`) — not loaded by default, and easy to lose track of after a `module purge`. If `case.build` fails at the very last step with a `manage_externals` provenance error mentioning `git` or `svn` not found, either load the relevant module or rerun with `./case.build --skip-provenance-check`.

### 7.3 GitHub's SVN bridge is permanently gone

One external (`cosp2`, referenced by `components/cam/Externals_CAM.cfg`) was configured to fetch via `svn checkout` against a GitHub URL — a trick that relied on GitHub's SVN-compatibility bridge, which GitHub permanently removed on January 8, 2024. This is unfixable by any local configuration; the workaround is to `git clone` the real repository (`https://github.com/CFMIP/COSPv2.0.git`) and manually check out the same tag (`v2.1.4cesm`), then copy just the `src` subdirectory to the path `checkout_externals` expected (`components/cam/src/physics/cosp2/src`).

---

## 8. Chronological summary of build errors and fixes (quick-reference table)

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | `gcc: error: unrecognized command line option '-fp-model'` building `gptl` | `intel-oneapi-mpi`'s `mpicc` wraps GCC, not Intel, despite `MPILIBS=openmpi` | Swap to real Intel-built `openmpi/4.1.2-intel-2021.5.0` module |
| 2 | `Can't locate XML/LibXML.pm` in CLM's `build-namelist` | System Perl lacks the module; CPAN install silently corrupted | Perl-5.26-pinned conda env + `PERL5LIB` (not `PATH`) |
| 3 | `NETCDF not found` building `mct` | No `NETCDF_C_PATH`/`NETCDF_FORTRAN_PATH` defined for `levante` in `config_compilers.xml` | Add machine-specific compiler block |
| 4 | Same NETCDF error persisted after fix | `Macros.make` not regenerated (stale) | `rm Macros.make Macros.cmake && ./case.setup` |
| 5 | `ImportError: cannot import name 'get_standard_makefile_args'` | `cime5.6.32` (from `release-cesm2.1.3`) lacks this function | Override `[cime]` in `Externals.cfg` to `cime5.8.16` |
| 6 | Re-porting needed after CIME swap | New CIME version, different file layout/schema in places | Re-applied machine-port XML into the new checkout (same monolithic-file convention, thankfully) |
| 7 | `Fatal attempt to include C++ code on a compiler/machine combo that has not been set up to support C++` | `SUPPORTS_CXX`/`SCC`/`SCXX`/`SFC` not resolving from the generic Intel block for our machine | Duplicate these settings directly in the `MACH="levante"` compiler block |
| 8 | `/mkSrcfiles: Command not found`, then various `No rule to make target 'lib*.a'` | CLM/CICE/MOSART/CISM build scripts omit `CASEROOT`/`CASETOOLS` from their hand-rolled `gmake` commands | Replace with `CIME.buildlib.run_gmake()` (Python) / add `CASEROOT=$CASEROOT` (Perl, CISM) |
| 9 | CISM: `FC=` empty, falls back to system `gfortran`, `mpi.mod` not found | CISM's CMake-based build doesn't correctly inherit `FC` on this system | Sidestepped: use `SGLC` compset instead of `CISM2%NOEVOLVE` (CISM irrelevant to this project anyway) |
| 10 | Various `error #6279`/`#6404`/`#6975`/`#6683`: kind parameter has no type | Several CLM/CICE source files reference `SHR_KIND_*` names that were never imported/don't exist in that file's scope | Fix each file's kind import/alias individually (§6.3–6.5) |
| 11 | `error #6285: no matching specific subroutine ... SEQ_INFODATA_GETDATA` | `lnd_resume` argument doesn't exist in `cime5.8.16`'s driver interface — real feature gap | Stub out `lnd_handle_resume` (§6.6) |
| 12 | `ld: cannot find -lmkl_intel_lp64` etc. at final link | `intel-oneapi-mkl` module never loaded | Add `intel-oneapi-mkl/2022.0.1-gcc-11.2.0` to module list |
| 13 | `Could not find a matching MPI for attributes` after MKL edit | Unrelated case-state corruption from a manual `rm env_mach_specific.xml` (not the MKL edit itself — confirmed by reverting and retesting) | Recreate the case fresh |
| 14 | `manage_externals` provenance-check errors (`git`/`svn` not found) | Modules purged earlier in session, never fully reloaded | `module load git ...` or `--skip-provenance-check` |

---

## 9. What's still open (from the original `HANDOFF.md`, still unresolved)

1. **Two missing input datasets**, same as originally flagged:
   - Base aircraft emission NetCDF forcing files (referenced via `air_specifier` in CAM's namelist)
   - MERRA2 nudging meteorology files for the specified-dynamics setup
   - Both need to come from the colleague directly, or from NCAR/NASA data archives — not in the public Zenodo record.
2. **Actual case run has not yet been attempted** — this log covers `case.build` succeeding only. `case.submit` and checking the run actually produces sensible output is the next milestone once input data is sorted.
3. **Resolution**: still at cheap validation resolution (`f19_f19_mg17`, ~2°). The paper's actual resolution is `f09`-class (~1°), 32 levels. Move to that once a full run-cycle is validated at low-res.
4. **CISM was sidestepped, not fixed.** If a future compset genuinely needs active ice-sheet dynamics, CISM's CMake/Intel-Fortran-detection issue (item 9 in the table above) will need real investigation.
5. **Colleague's actual CAM/CIME tag and machine** — still unconfirmed. Once his setup arrives, reconcile against everything in this log rather than assuming compatibility.
6. **`run_gmake()`'s silent failure-swallowing** (§6.1) is a standing trap for any future SourceMods work on CLM/CICE/MOSART — a real compile error in these components will not stop the build or produce a clear error; it'll surface later as a missing-library link failure. Worth remembering when debugging future build issues in these three components specifically.

---

## 10. Reproduction runbook (condensed)

For rebuilding on a fresh checkout (e.g. after this one is lost, or setting up a second case):

```bash
# 1. Clone and pin versions
git clone https://github.com/ESCOMP/CESM.git my_cesm_sandbox
cd my_cesm_sandbox
git checkout release-cesm2.1.3
sed -i 's/tag = cime5.6.32/tag = cime5.8.16/' Externals.cfg
sed -i 's/tag = cam_cesm2_1_rel_41/tag = cam6_2_020/' Externals.cfg

# 2. Fetch externals (needs python3, subversion modules loaded)
module load python3/2023.01-gcc-11.2.0 subversion git/2.43.7-gcc-11.2.0
./manage_externals/checkout_externals

# 3. Manually fix the dead GitHub-SVN cosp2 external (see §7.3)
git clone https://github.com/CFMIP/COSPv2.0.git /tmp/cospv2_tmp
cd /tmp/cospv2_tmp && git checkout v2.1.4cesm && cd -
mkdir -p components/cam/src/physics/cosp2
cp -r /tmp/cospv2_tmp/src components/cam/src/physics/cosp2/src
rm -rf /tmp/cospv2_tmp

# 4. Apply the machine-port + source patches from the backup repo
git apply ~/levante_port_backup/patches/cime.patch --directory=cime
git apply ~/levante_port_backup/patches/clm.patch --directory=components/clm
git apply ~/levante_port_backup/patches/cice.patch --directory=components/cice
git apply ~/levante_port_backup/patches/mosart.patch --directory=components/mosart
git apply ~/levante_port_backup/patches/cism.patch --directory=components/cism
# (run each from inside my_cesm_sandbox; adjust --directory if applying from elsewhere)

# 5. Recreate the Perl environment if needed
mamba create --prefix /work/bd1062/b309257/conda_envs/cesm-perl526 \
  -c bioconda -c conda-forge "perl=5.26" perl-xml-libxml -y

# 6. Build
module load python3/2023.01-gcc-11.2.0
./cime/scripts/create_newcase \
  --case cam6-contrail-cirrus/cases/<casename> \
  --compset HIST_CAM60_CLM50%SP_CICE%PRES_DOCN%DOM_MOSART_SGLC_SWAV \
  --res f19_f19_mg17 \
  --machine levante \
  --compiler intel \
  --run-unsupported
cd cam6-contrail-cirrus/cases/<casename>
./case.setup
./case.build
```

Note: step 4's `git apply` needs testing — patches were captured via `git diff` from a dirty working tree during an interactive session, not pre-tested as a clean apply-from-scratch. If `git apply` complains about conflicts, the safer fallback is to manually re-apply each change described in §3–§6 above by hand, using this log as the reference.
