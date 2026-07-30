# Levante CESM2/CAM6.2 Port Log — Gettelman et al. (2021) Replication

**Date:** 2026-07-27 to 2026-07-28
**Machine:** DKRZ Levante, account `bd1062` / user `b309257`
**Goal:** A working CESM2/CAM6.2 executable on Levante, using the exact CAM tag (`cam6_2_020`) verified against the Gettelman et al. (2021) COVID-contrail paper's Zenodo dataset, as groundwork before the work is extended by SAF/H2 contrail-cirrus parameterisations.

This document covers the full path from zero to a successfully completed test simulation: machine porting, build, input-data acquisition, and runtime debugging. It supersedes the build-mechanics portions of the original `HANDOFF.md` — that document remains the reference for science background, CAM source review, and the still-open MERRA2/aircraft-emission data gap.

Status at time of writing: case builds and runs cleanly (5-timestep smoke test, `HIST` compset, `f19_f19_mg17` resolution). The specified-dynamics/COVID-emissions science setup described in the paper is not yet implemented — see §12. (This has since progressed substantially on the `cam6_2_022` branch — soft nudging, aircraft emissions, and SSP2-4.5 forcing are now working together at f09 resolution; see `CONTRAIL_SOURCEMODS_INTEGRATION_LOG.md`.)

---

## 1. Final working configuration

- **Top-level checkout:** `https://github.com/ESCOMP/CESM.git`, tag `release-cesm2.1.3`.
- **CIME version:** overridden via `Externals.cfg`'s `[cime]` entry to `cime5.8.16` (the default `cime5.6.32` lacks a function CAM's build script requires; `cime5.8.16` is also what CAM's own internal `Externals.cfg` recommends).
- **CAM tag:** `Externals.cfg`'s `[cam]` entry overridden to `cam6_2_020`.
- **All other externals** (CLM, CICE, MOSART, CISM, etc.): default pins from `release-cesm2.1.3`.
- **Compset:** `HIST_CAM60_CLM50%SP_CICE%PRES_DOCN%DOM_MOSART_SGLC_SWAV` (explicit longname, not the `FHIST` alias — see §5.3).
- **Grid:** `f19_f19_mg17` (~2°, for validation; move to `f09`-class ~1° for the paper's actual resolution later).
- **Compiler/module stack**, in load order:
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
  Preceded by an explicit `module purge` (§8.3). `intel-oneapi-mpi` is not used — its bundled `mpicc` wraps GCC rather than `icc` on this system; `MPILIBS=openmpi` with the real Intel-compiled OpenMPI is required instead.
- **Runtime library paths:** none of the above modules populate `LD_LIBRARY_PATH`. Five library directories are set explicitly via `<environment_variables>` in the machine config — see §9.
- **Perl for CLM's namelist step:** system Perl (5.26.3) lacks `XML::LibXML`. A Perl-5.26-pinned conda environment at `/work/bd1062/b309257/conda_envs/cesm-perl526` (bioconda `perl-xml-libxml`) is wired in via `PERL5LIB`, not `PATH` (to avoid the environment's own `mpicc` shadowing the Intel/OpenMPI one).
- **`CLM_FORCE_COLDSTART=on`**: set for the test case to bypass a crash in CLM's `init_interp` routine (§11).
- **Directory layout:**
  - Code checkout: `~/my_cesm_sandbox` (HOME)
  - Input data / archived output: `/work/bd1062/b309257/cam6-contrail-cirrus/` (WORK)
  - Active run directories: `/scratch/b/b309257/<casename>` (SCRATCH, 14-day auto-purge)
  - Port backup (git repo, patches + this log): `~/levante_port_backup`, mirrored to GitHub

---

## 2. Core version mismatch

`cam6_2_020` is an intermediate CAM development snapshot from April 2020, between the CAM tags pinned by `release-cesm2.1.2`/`release-cesm2.1.3` (`cam_cesm2_1_rel_41`, January 2020) and `release-cesm2.2.0` (`cam_cesm2_2_rel_02`, later 2020). No top-level CESM release tag pins `cam6_2_020` directly (confirmed by comparing commit dates in the CAM submodule's own git history).

Two consequences:

1. CIME API mismatch: `release-cesm2.1.3`'s default CIME (`cime5.6.32`) lacks the `get_standard_makefile_args` function CAM's `buildlib` script imports. The function exists in `cime5.8.16`, which is also what CAM's own internal `Externals.cfg` recommends. Fix: override the top-level CIME external to `cime5.8.16`, keeping the CESM2.1.3-era CLM/CICE/MOSART/CISM.

2. CIME driver-interface mismatch: CLM's tagged source calls a data-assimilation-resume function (`seq_infodata_GetData(..., lnd_resume=...)`) absent from `cime5.8.16`'s `seq_infodata_mod` entirely — a feature gap, not a naming difference. Fixed by stubbing out the one subroutine using it (§6.6), since DA-resume is unrelated to this project.

Reconciling against the colleague's actual CAM/CIME tag combination, once available, is a priority — see §12.

---

## 3. Machine port: `config_machines.xml`

This CIME line uses a monolithic `config_machines.xml` at `cime/config/cesm/machines/config_machines.xml` — no per-machine subdirectory fragments (that convention belongs to a later CIME generation).

Final `<machine>` block:

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
      <command name="purge"/>
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
    <env name="LD_LIBRARY_PATH">/sw/spack-levante/intel-oneapi-mkl-2022.0.1-ttdktf/mkl/2022.0.1/lib/intel64:/sw/spack-levante/intel-oneapi-compilers-2022.0.1-an2cbq/compiler/2022.0.1/linux/compiler/lib/intel64_lin:/sw/spack-levante/openmpi-4.1.2-yfwe6t/lib:/sw/spack-levante/netcdf-c-4.8.1-2k3cmu/lib:/sw/spack-levante/netcdf-fortran-4.5.3-k6xq5g/lib:/sw/spack-levante/parallel-netcdf-1.12.2-mc24h4/lib</env>
  </environment_variables>
</machine>
```

Notes:
- `OS` is `LINUX`, not `CNL` (Cray-specific — an early draft, adapted from a Perlmutter template, used `CNL` incorrectly).
- `module_system type="module"`, not Lmod — Levante uses classic Tcl-based Environment Modules (`$MODULESHOME=/usr/share/Modules`).
- The `purge` command at the start of `<modules>` is required. SLURM's default `--export=ALL` inherits the submitting shell's environment into the batch job; without an explicit purge, an incomplete or inconsistent environment in the submitting shell can leak into the job and interfere with the module loads that follow.
- `NODENAME_REGEX` is a per-machine element in this schema version (not a centralized top-level block, which is a later-CIME convention). It has no functional effect here since `create_newcase --machine levante` always sets the machine explicitly.
- `PROJECT_REQUIRED` must follow `mpirun` in the schema's element sequence: `... MAX_MPITASKS_PER_NODE, COSTPES_PER_NODE, PROJECT_REQUIRED, mpirun, module_system, environment_variables, resource_limits`.
- `$ENV{...}` substitutions inside this file are resolved at `case.setup` time, in whatever shell is running that command — not dynamically at job-run time on the compute node. An earlier draft of the `LD_LIBRARY_PATH` entry used `:$ENV{LD_LIBRARY_PATH}` intending to append to the runtime shell's existing value; this failed with `ERROR: Undefined env var 'LD_LIBRARY_PATH'` whenever the interactive shell running `case.setup` had that variable unset, which is the common case for a shell that has not loaded any modules yet. The fix was to drop the `$ENV{}` reference and set the five library paths directly.

### 3.1 `env_mach_specific.xml` regeneration

This case-level file, derived from `config_machines.xml`, does not reliably regenerate through `case.setup --clean` followed by `case.setup` — that cycle only rewrites batch scripts, not this file. Manually deleting it and rerunning `case.setup` is also unsafe: doing so reproducibly triggers `ERROR: Could not find a matching MPI for attributes: {...}`, regardless of `config_machines.xml`'s actual content — some other case-state file expects a controlled transition that a raw deletion skips.

The only mechanism found to reliably force full regeneration after a machine-config change is deleting the case directory and recreating it (`create_newcase`, answering `u` — use existing — when prompted about the pre-existing `bld`/`run` directories in `/scratch`, which avoids a full recompile). This was needed three times over the course of this port (once for the MKL module addition, once for the `LD_LIBRARY_PATH` `$ENV{}` fix, once for the complete `LD_LIBRARY_PATH` value).

### 3.2 Regenerating `Macros.make` after a `config_compilers.xml` change

Separately, `case.setup` only regenerates `Macros.make` if the file does not already exist — editing `config_compilers.xml` for an existing case does not propagate automatically. Fix:
```bash
rm Macros.make Macros.cmake
./case.setup
```

---

### 3.3 Keeping saved patches in sync with the live config

When setting up a second, parallel port (`cam6_2_022`, see the
`cesm2.1.3-cime5.8.16-cam6_2_022` branch), reapplying the patches saved in
this repository produced a case with no `LD_LIBRARY_PATH` entry in
`env_mach_specific.xml` at all, despite `git diff --stat` showing
`config_machines.xml` as changed. The saved `cime.patch` had been exported
early in the original session, before the runtime-library fixes in §9 were
made to the live `config_machines.xml` — and was never re-exported
afterward, so it silently carried a stale (pre-fix) version of the file.
`git apply` succeeds identically whether a patch is current or stale, so
this doesn't surface until something built from the saved patch behaves
differently from the live setup, often much later and looking like a new
bug rather than an old, un-synced fix.

Lesson: any time the live machine config is edited after a patch has
already been exported and saved, the patch needs re-exporting (`git diff`
in the live checkout, overwrite the saved `.patch` file) before it can be
trusted as an accurate record. (This happened a second time with a
stack-size `resource_limits` fix added for f09 resolution — see
`CONTRAIL_SOURCEMODS_INTEGRATION_LOG.md` §10 — which as of this writing
has been synced to the `cam6_2_022` branch's patch but not yet to this
branch's.)

## 4. Machine port: `config_batch.xml`

Monolithic file, `cime/config/cesm/machines/config_batch.xml`. Uses `<arg flag="..." name="..."/>` syntax for `submit_args`:

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

`-p` is SLURM's real partition flag (some machine templates use a site-specific `-q` alias, which does not apply here). `nodemax` values are placeholders, not confirmed against DKRZ's actual per-job limits.

CIME's own generated `.case.run` script already sets `--job-name`, `--nodes`, `--ntasks-per-node`, `--output`, and `--exclusive` correctly, derived from the case's PE layout — no additional `sbatch` flags are needed beyond what CIME produces.

---

## 5. Machine port: `config_compilers.xml`

Monolithic file, `cime/config/cesm/machines/config_compilers.xml`. This schema uses `xs:choice` (order-independent), unlike the two files above.

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

A generic `<compiler COMPILER="intel">` block already sets `SCC`/`SCXX`/`SFC`/`SUPPORTS_CXX`, but a machine-specific block that leaves these unset does not appear to inherit them from the compiler-generic block — CLM's build failed with "Fatal attempt to include C++ code on a compiler/machine combo that has not been set up to support C++" until they were duplicated directly here. The exact precedence rule was not fully determined; duplicating the values was sufficient and reliable.

`NETCDF_C_PATH`/`NETCDF_FORTRAN_PATH` (split form) are used because Levante's `netcdf-c` and `netcdf-fortran` are separate Spack install prefixes, not a combined directory.

### 5.3 Compset choice: `SGLC` instead of `CISM2%NOEVOLVE`

With `cime5.8.16`, the `FHIST` compset alias resolves to a longname including `CISM2%NOEVOLVE` (full CISM ice-sheet component, evolution disabled) and an `SIAC` stub. CISM's CMake-based build did not correctly inherit the `FC` environment variable on this system, falling back to system `gfortran`, which then failed to find MPI modules built for Intel. Since CISM is unrelated to the contrail-cirrus science, it was avoided entirely by requesting the explicit compset longname with `SGLC` (stub glacier) in place of `CISM2%NOEVOLVE`:

```
HIST_CAM60_CLM50%SP_CICE%PRES_DOCN%DOM_MOSART_SGLC_SWAV
```

`create_newcase` auto-adds `SIAC`/`SESP` stub components regardless of this choice.

---

## 6. Source-code and script patches

Captured as git diffs in `~/levante_port_backup/patches/` (`cime.patch`, `clm.patch`, `cice.patch`, `mosart.patch`, `cism.patch`).

### 6.1 `components/clm/cime_config/buildlib`, `components/cice/cime_config/buildlib`, `components/mosart/cime_config/buildlib`

These three scripts hand-construct their `gmake` invocation as a literal string, omitting `CASEROOT` (and, for CLM, `CASETOOLS`) entirely. Since `Tools/Makefile` does `include $(CASEROOT)/Macros.make`, a missing `CASEROOT` silently fails to find the macros file, producing a `NETCDF not found` error that appears environmental but is not.

The fix used CIME's own `CIME.buildlib.run_gmake()` helper, which calls `get_standard_makefile_args()` internally and supplies every standard variable at once, rather than patching individual missing arguments as they surfaced.

CLM (`clm5_0` branch only; `clm4_0` untouched):
```python
else:
    run_gmake(case, "clm", libroot, bldroot, libname="clm")
```

CICE:
```python
run_gmake(case, "ice", libroot, bldroot, libname="ice", user_cppdefs=cice_cppdefs)
```

MOSART:
```python
run_gmake(case, "rof", libroot, bldroot, libname="rof")
```

`run_gmake()`'s own implementation does not check the underlying command's return code — a compile failure in one of these three components is silently swallowed and reported as a normal build completion, surfacing only later as a missing-library error at the final link step. When a build reports success unusually quickly, or the final link fails to find a `.a` file for a component that reported success, the component's own `.bldlog` file needs to be checked directly for the real error.

### 6.2 `components/cism/cime_config/buildlib` (Perl)

Same missing-`CASEROOT` pattern, in Perl. Two `$sysmod` strings required `CASEROOT=$CASEROOT` appended. This became moot once CISM was excluded from the compset (§5.3), and is recorded here in case CISM is re-enabled in the future.

### 6.3 `components/clm/src/biogeophys/UrbanTimeVarType.F90`

A declaration used `SHR_KIND_CL` (the fully-qualified name) where the file only imports the kind under the local alias `CL`. Fixed:
```fortran
character(SHR_KIND_CL)  :: fldList   →   character(len=CL)       :: fldList
```

### 6.4 `components/clm/src/biogeochem/SatellitePhenologyMod.F90`, `components/clm/src/biogeophys/SoilMoistureStreamMod.F90`

Same pattern, different kind (`SHR_KIND_CXX`, a distinct 4096-character kind constant, not a typo for `CL`). Neither file imported it. Fixed by adding the import and using the local alias in both files:
```fortran
use shr_kind_mod    , only : CXX => shr_kind_CXX
character(SHR_KIND_CXX)    :: fldList   →   character(len=CXX)        :: fldList
```

### 6.5 `components/cice/src/source/ice_atmo.F90`, `components/cice/src/drivers/cesm/ice_prescribed_mod.F90`

Same pattern in CICE's own kind system (`ice_kinds_mod`, unrelated to `shr_kind_mod`). `SHR_KIND_R8`/`SHR_KIND_IN` were never valid names in these files; the correct local names, already used elsewhere in the same files, are `dbl_kind`/`int_kind`.
```fortran
ustar_prev = 2.0_SHR_KIND_R8 * ustar   →   ustar_prev = 2.0_dbl_kind * ustar
integer(SHR_KIND_IN),parameter :: nFilesMaximum = 400   →   integer(kind=int_kind),parameter :: nFilesMaximum = 400
```

Two further files matched the same `SHR_KIND_*` pattern in a repository-wide search (`components/clm/src/unit_test_stubs/csm_share/shr_mpi_mod_stub.F90`, `components/cice/src/csm_share/shr_orb_mod.F90`) but were left unmodified: neither caused an actual build failure in this compset, one has the relevant `use` statement already commented out, and the other is a unit-test stub not exercised by a standard build.

### 6.6 `components/clm/src/cpl/lnd_comp_mct.F90` — `lnd_handle_resume` stubbed out

This subroutine calls `seq_infodata_GetData(infodata, lnd_resume=lnd_resume)`. `lnd_resume` does not exist anywhere in `cime5.8.16`'s `seq_infodata_mod.F90` — a driver-interface gap (§2), not a naming issue. This is CLM's data-assimilation resume-signal handling, unrelated to contrail-cirrus science. The subroutine body was replaced with a no-op, keeping the signature intact so its two call sites (lines 262 and 380 of the same file) still compile:
```fortran
subroutine lnd_handle_resume( infodata )
  ! NOTE: disabled -- lnd_resume is not available in this CIME driver version (cime5.8.16);
  ! not needed for this project (no data assimilation is used).
  use seq_infodata_mod , only : seq_infodata_type
  implicit none
  type(seq_infodata_type), intent(IN) :: infodata
end subroutine lnd_handle_resume
```

---

## 7. Environment / dependency setup

### 7.1 `XML::LibXML` for Perl

CLM's `build-namelist` script needs `XML::LibXML`, absent from system Perl (5.26.3). CPAN (`cpanm`) repeatedly reported successful installation while silently failing to place files — a `make`/`pm_to_blib` staging issue not fully root-caused, possibly a stale-timestamp artifact across filesystem mounts.

Fix: installed via bioconda instead, pinned to Perl 5.26 to match system Perl's ABI (XS/compiled-extension compatibility requires matching major.minor Perl versions):
```bash
mamba create --prefix /work/bd1062/b309257/conda_envs/cesm-perl526 \
  -c bioconda -c conda-forge "perl=5.26" perl-xml-libxml -y
```
Wired in via `PERL5LIB`, not `PATH` — activating the conda environment directly would also put its own `mpicc` on `PATH`, shadowing the Intel/OpenMPI one and reintroducing the compiler mismatch in §1. Two library paths are needed (architecture-specific for the compiled extension, plus a pure-Perl path for `XML::SAX::Exception`):
```
/work/bd1062/b309257/conda_envs/cesm-perl526/lib/site_perl/5.26.2/x86_64-linux-thread-multi
/work/bd1062/b309257/conda_envs/cesm-perl526/lib/site_perl/5.26.2
```

A separate, non-pinned conda environment (`cesm-perl`, Perl 5.32) exists at `/work/bd1062/b309257/conda_envs/cesm-perl` and works standalone, but its Perl version does not match system Perl's ABI and it is not used by the final machine config.

### 7.2 `svn` and `git` modules

Both needed intermittently — `subversion` for the `chem_proc`/`carma` external checkouts and for input-data fetching (§8), `git` for CESM's externals and the build's provenance-recording step. Neither loads by default and both are easy to lose after `module purge`. A build or submission failing at its last step with a `manage_externals` error mentioning `git` or `svn` not found is fixed by loading the relevant module, or by rerunning with `--skip-provenance-check`.

### 7.3 GitHub's SVN bridge is permanently gone

One external (`cosp2`, in `components/cam/Externals_CAM.cfg`) was configured to fetch via `svn checkout` against a GitHub URL, relying on a compatibility bridge GitHub permanently removed on January 8, 2024. Workaround: clone the real repository and check out the matching tag, then copy the needed subdirectory to the path `checkout_externals` expected:
```bash
git clone https://github.com/CFMIP/COSPv2.0.git /tmp/cospv2_tmp
cd /tmp/cospv2_tmp && git checkout v2.1.4cesm && cd -
mkdir -p components/cam/src/physics/cosp2
cp -r /tmp/cospv2_tmp/src components/cam/src/physics/cosp2/src
```

---

### 7.4 Nested optional externals: `clubb`, `silhs`, `atmos_phys`, `fates`

Building a second CAM tag (`cam6_2_022`) from a fresh checkout failed with
compile errors in `clubb_intr.F90` and `clmfates_paraminterfaceMod.F90` —
both "error #7002: Error in opening the compiled module file," meaning the
underlying external source was entirely absent rather than just
misconfigured. The working `cam6_2_020` checkout has these same source
directories (`components/cam/src/physics/clubb`, `components/clm/src/fates`)
populated, despite both tags marking `required = True` for these externals
in their respective `Externals_CAM.cfg`/`Externals_CLM.cfg` files.

Per `checkout_externals --help`: by default, only the externals listed
directly in the top-level `Externals.cfg` are checked out. Nested externals
-- those listed inside a sub-project's own `Externals_CAM.cfg`/
`Externals_CLM.cfg`, such as `clubb`, `silhs`, `atmos_phys`, and `fates` --
are treated as optional regardless of their own internal `required` flag,
unless targeted explicitly. The `-o` ("also checkout optional externals")
flag does not reach into nested files either; each optional nested external
must be fetched by name, pointed at its own specific `Externals_*.cfg`:

```bash
cd components/cam
../../manage_externals/checkout_externals -e Externals_CAM.cfg -o clubb silhs atmos_phys

cd ../clm
../../manage_externals/checkout_externals -e Externals_CLM.cfg -o fates
```

Two things worth knowing about this step:

1. `checkout_externals` refuses to fetch anything (even unrelated
   externals) if it detects any repository already in a modified/"dirty"
   state -- which applying the CLM/CICE/MOSART/CISM source patches (§6)
   triggers immediately. Fetch everything, including these optional
   externals, *before* applying source patches, not after. If patches are
   already applied when this is hit, temporarily revert them
   (`git checkout -- .` in each affected component directory), fetch, then
   reapply.
2. This same requirement almost certainly applied to the original
   `cam6_2_020` setup too, since its `clubb`/`fates` source is present --
   but the step wasn't captured in this log at the time it was actually
   done. Treat the reproduction runbook (§13) as relying on this having
   been done manually at some point during the original session.

## 8. Input data acquisition

`./check_input_data` lists every file a compset needs under `DIN_LOC_ROOT`; `--download` attempts to fetch missing ones automatically.

### 8.1 FTP is blocked outbound

The default input-data server entry in `cime/config/cesm/config_inputdata.xml` uses `ftp://ftp.cgd.ucar.edu` (via `wget`). This failed to connect entirely — FTP (port 21) being blocked outbound on Levante's login nodes is the most likely cause, consistent with typical HPC firewall policy. The same file lists an SVN-over-HTTPS alternative, which does connect:
```bash
module load subversion
./check_input_data --download --protocol svn --server https://svn-ccsm-inputdata.cgd.ucar.edu/trunk/inputdata
```

### 8.2 CIME's downloader over-fetches via directory-level SVN checkout

A first `--download` attempt, left running, accumulated over 20 GB before being stopped, including entire subdirectories (`atm/cam/tracer_cnst`, `atm/cam/ozone_strataero`, `atm/cam/solar`, `atm/waccm`, and an unrelated `cesm2_init` restart-file directory) far beyond what the missing-file list actually named. CIME's SVN download mechanism appears to check out whole containing directories rather than exporting individual files.

Fix: extract the unique set of needed file paths from `check_input_data`'s output, then fetch each with a targeted `svn export` (which retrieves a single file without pulling its containing directory):
```bash
grep -oP "= '\K[^']+" missing_files.txt | sort -u > unique_missing_files.txt

LOCAL_ROOT="/work/bd1062/b309257/cam6-contrail-cirrus/inputdata"
REMOTE_BASE="https://svn-ccsm-inputdata.cgd.ucar.edu/trunk/inputdata"
while read -r localfile; do
  relpath="${localfile#$LOCAL_ROOT/}"
  mkdir -p "$(dirname "$localfile")"
  [ -f "$localfile" ] || svn export --force "$REMOTE_BASE/$relpath" "$localfile"
done < unique_missing_files.txt
```

### 8.3 Final input-data size is large, not further over-fetching

Even with the targeted per-file fetch, total input data reached roughly 55 GB. The breakdown confirmed this is not further over-fetching: the specific named files required by this compset — `ozone_strataero` (stratospheric ozone/aerosol climatology, full 1850–2015 period at 5-day frequency, 70 vertical levels), `tracer_cnst` (constant-species vertical profiles, similar span/resolution), and the CMIP6 3D vertical emission fields — are each, individually, tens of gigabytes at this temporal/vertical resolution. This is inherent to the datasets these compset settings require, not an artifact of the fetch mechanism.

After the targeted fetch completed, `./check_input_data` (without `--download`) returned with no missing files reported for any component.

---

## 9. Runtime library resolution (`LD_LIBRARY_PATH`)

None of Levante's Spack-provided modules used in this build populate `LD_LIBRARY_PATH` — confirmed by loading the full module stack fresh and finding the variable completely empty. This is a systemic property of these modules (they set `PATH`/`INCLUDE`/`PKG_CONFIG_PATH` for compile-time use, consistent with a Spack deployment that assumes RPATH-based linking rather than runtime `LD_LIBRARY_PATH` resolution), not specific to any one library.

Because `cesm.exe`'s final link step does not embed RPATH entries for these libraries, the executable fails at runtime with `error while loading shared libraries: <libname>: cannot open shared object file`, even though the link succeeded at build time. This surfaced incrementally, one library at a time, across several submission attempts: first `libmkl_intel_lp64.so.2`, then (once MKL was fixed) `libnetcdff.so.7`.

Rather than continue fixing libraries one at a time as they surfaced, the five relevant library directories were identified together (via `module show <name> | grep prepend` for the actual install prefixes, and `find`/`module show` for MKL and the Intel compiler runtime) and set at once:
```
/sw/spack-levante/intel-oneapi-mkl-2022.0.1-ttdktf/mkl/2022.0.1/lib/intel64
/sw/spack-levante/intel-oneapi-compilers-2022.0.1-an2cbq/compiler/2022.0.1/linux/compiler/lib/intel64_lin
/sw/spack-levante/openmpi-4.1.2-yfwe6t/lib
/sw/spack-levante/netcdf-c-4.8.1-2k3cmu/lib
/sw/spack-levante/netcdf-fortran-4.5.3-k6xq5g/lib
/sw/spack-levante/parallel-netcdf-1.12.2-mc24h4/lib
```

These paths include a Spack-generated build hash (e.g. `ttdktf`, `2k3cmu`, `mc24h4`) tied to that exact module build. If any of these modules is rebuilt under the same version number with a different hash, the corresponding path here goes stale, reproducing the same "cannot open shared object file" failure. HPC centers typically add new module builds alongside existing ones rather than replacing them in place, which limits how often this is likely to occur, but the path is not guaranteed stable indefinitely. If `module load` for any of these starts failing, or a previously-working run suddenly hits a missing-library error, re-deriving these paths via `module show <name> | grep prepend` is the first check to make.

ESMF's library directory is not included: `USE_ESMF_LIB=FALSE` for this build (visible in the final link command), so it is not linked at runtime.

---

## 10. Cascading effect of case-state changes

Three distinct case-level files each have their own regeneration rule, established through repeated trial:

| File | Regenerates via `case.setup --clean` + `case.setup`? | Regenerates via manual deletion + `case.setup`? | Reliable method |
|---|---|---|---|
| `Macros.make` | No (only created if absent) | Yes | Delete, then `case.setup` |
| `env_batch.xml` | Yes | — | `case.setup --clean` + `case.setup` |
| `env_mach_specific.xml` | No | No — produces `Could not find a matching MPI` error | Full case recreation (`create_newcase`, answer `u` to reuse existing `bld`/`run`) |

A machine-config change that affects any of these should be checked against this table before assuming a simple `case.setup` cycle picked it up. Silently stale files were the cause of at least three repeated submission failures during this port, each initially appearing as though the underlying fix had not worked when in fact it had simply not yet been read.

---

## 11. CLM `init_interp` failure at runtime — cold start

With the runtime libraries resolved (§9), a first full submission ran for approximately 30–50 seconds before failing with `SIGTERM` inside CLM's `initInterp.F90`, called from `clm_initializeMod.F90`, itself called during `lnd_comp_mct.F90`'s initialization. The stack trace showed the failure occurring during an `MPI_Bcast` inside PIO's read path.

The compset's default land initial-conditions file (`finidat`) is `clmi.BHIST.2000-01-01.0.9x1.25_gx1v7_simyr2000_c181015.nc` — natively at 0.9°×1.25° resolution — while the test case runs at 1.9°×2.5° (`f19`). This resolution mismatch invokes CLM's `init_interp` machinery to regrid the initial conditions on the fly; something in that regridding path (possibly related to `PIO_VERSION=1`, used by this build, at a 256-task count) failed during a collective MPI operation.

Since the test's purpose is confirming the executable runs, not producing scientifically valid land initial conditions, the fix used was a cold start, which bypasses `finidat`/`init_interp` entirely:
```bash
./xmlchange CLM_FORCE_COLDSTART=on
```
With this set, the 5-timestep run completed with `COMPLETED`/exit code `0:0` for every step of both `case.run` and `case.st_archive`, and produced a complete, consistent set of restart files for every component (`cam`, `cice`, `clm2`, `cpl`, `docn`, plus routing pointers) at the expected final timestamp.

This same `init_interp` code path will need revisiting once the case moves to using scientifically appropriate initial conditions rather than a cold start — the underlying MPI/PIO1 failure was not root-caused, only avoided.

---

## 12. Still open

1. MERRA2 nudging files and aircraft-emission forcing data are not part of the standard input-data set fetched in §8 and are not available from NCAR's public server — these need to come from the colleague directly, per the original `HANDOFF.md`. (Resolved on the `cam6_2_022` branch — see `CONTRAIL_SOURCEMODS_INTEGRATION_LOG.md`.)
2. The contrail-cirrus SourceMods (`ssatcontrail.F90`, `aircraft_emit.F90`, `tracer_data.F90`, `physpkg.F90`, `horizontal_interpolate.F90`, already downloaded from the paper's Zenodo record) have not yet been placed into `SourceMods/src.cam/` or built. (Done on the `cam6_2_022` branch.)
3. COVID emission scaling (`weekly_flight_fraction_2020all.nc`, already downloaded) is not yet wired into the namelist. (Done on the `cam6_2_022` branch, and since extended with a real 2019 seasonal pattern — see `CONTRAIL_SOURCEMODS_INTEGRATION_LOG.md` §15-16.)
4. The test case is the plain `HIST` compset — free-running, prescribed ocean/ice, full 1850–2017 historical SST forcing — not the specified-dynamics/MERRA2-nudged setup the paper actually uses. (The `%SDYN` compset was tried and dropped in favor of `nudging_nl` soft nudging on the same plain compset — see `CONTRAIL_SOURCEMODS_INTEGRATION_LOG.md` §8. SST forcing is still the historical climatology, not MERRA2-derived SST as the paper describes — still open.)
5. Resolution is at `f19_f19_mg17` (~2°); the paper uses `f09`-class (~1°), 32 levels. (Moved to `f09_f09_mg17` on the `cam6_2_022` branch — see `CONTRAIL_SOURCEMODS_INTEGRATION_LOG.md` §9. This also surfaced a stack-overflow bug at the finer resolution, fixed there in §10, not yet synced to this branch's own `cime.patch`.)
6. CISM was excluded, not fixed (§5.3). Its CMake/Intel-Fortran `FC`-detection issue remains unresolved if ice-sheet dynamics are needed in the future.
7. CLM's `init_interp` failure (§11) was avoided via cold start, not root-caused. Any future case using a resolution-mismatched or otherwise-interpolated `finidat` file may hit the same failure.
8. The colleague's actual CAM/CIME tag and machine remain unconfirmed. Reconciling against this log once available is a priority, given how version-sensitive this entire port proved to be.
9. `run_gmake()`'s silent failure-swallowing (§6.1) remains a standing risk for any future SourceMods work on CLM/CICE/MOSART.
10. The five `LD_LIBRARY_PATH` entries in §9 contain Spack build hashes that could go stale if the underlying modules are ever rebuilt.

---

## 13. Reproduction runbook (condensed)

```bash
# 1. Clone and pin versions
git clone https://github.com/ESCOMP/CESM.git my_cesm_sandbox
cd my_cesm_sandbox
git checkout release-cesm2.1.3
sed -i 's/tag = cime5.6.32/tag = cime5.8.16/' Externals.cfg
sed -i 's/tag = cam_cesm2_1_rel_41/tag = cam6_2_020/' Externals.cfg

# 2. Fetch externals
module load python3/2023.01-gcc-11.2.0 subversion git/2.43.7-gcc-11.2.0
./manage_externals/checkout_externals

# 3. Fix the dead GitHub-SVN cosp2 external (see §7.3)
git clone https://github.com/CFMIP/COSPv2.0.git /tmp/cospv2_tmp
cd /tmp/cospv2_tmp && git checkout v2.1.4cesm && cd -
mkdir -p components/cam/src/physics/cosp2
cp -r /tmp/cospv2_tmp/src components/cam/src/physics/cosp2/src
rm -rf /tmp/cospv2_tmp

# 3b. Fetch optional nested externals not covered by the default checkout (see §7.4)
cd components/cam
../../manage_externals/checkout_externals -e Externals_CAM.cfg -o clubb silhs atmos_phys
cd ../clm
../../manage_externals/checkout_externals -e Externals_CLM.cfg -o fates
cd ../..

# 4. Apply the machine-port and source patches
git apply ~/levante_port_backup/patches/cime.patch --directory=cime
git apply ~/levante_port_backup/patches/clm.patch --directory=components/clm
git apply ~/levante_port_backup/patches/cice.patch --directory=components/cice
git apply ~/levante_port_backup/patches/mosart.patch --directory=components/mosart
git apply ~/levante_port_backup/patches/cism.patch --directory=components/cism

# 5. Recreate the Perl environment
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
./case.build --skip-provenance-check

# 7. Fetch input data (see §8 for the FTP-blocked/over-fetch caveats)
module load subversion
./check_input_data --download --protocol svn --server https://svn-ccsm-inputdata.cgd.ucar.edu/trunk/inputdata

# 8. Short test run
./xmlchange STOP_OPTION=nsteps
./xmlchange STOP_N=5
./xmlchange JOB_WALLCLOCK_TIME=00:30:00
./xmlchange CLM_FORCE_COLDSTART=on
./case.submit
```

`git apply` in step 4 has been confirmed to work cleanly against a fresh checkout: the same five patches were used to set up the parallel `cam6_2_022` branch from scratch, and all five applied without conflict. If `git apply` ever does report a conflict (e.g. against a different CAM tag with more divergent source), re-applying each change manually using §6 as the reference is the fallback. Note also that step 3b must run *before* step 4 -- `checkout_externals` refuses to fetch anything once it detects the source patches' modifications (see §7.4).
