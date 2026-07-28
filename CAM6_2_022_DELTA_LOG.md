# cam6_2_022 Branch — Delta Log

This branch is a parallel setup to `cesm2.1.3-cime5.8.16-cam6_2_020`, built to
match the CAM tag the Gettelman et al. (2021) paper's own "Code and data
availability" section explicitly cites: `https://github.com/ESCOMP/CAM/tree/cam6_2_022`.
The full account of the machine port, build process, input-data acquisition,
and runtime debugging is on the `cesm2.1.3-cime5.8.16-cam6_2_020` branch's
`LEVANTE_PORT_LOG.md` — everything there applies equally here except where
noted below. This document covers only what's different.

## Why this branch exists

The original setup used `cam6_2_020` (an intermediate CAM development
snapshot, chosen because it was verifiable against the paper's Zenodo
record's file timestamps). Comparing `cam6_2_020` against `cam6_2_022`
directly (`git log`/`git diff` between the two tags, both reachable in the
same local CAM checkout) showed:

- `cam6_2_022` itself is a pure externals/build update (repinning component
  tags, a build-config path fix for relocated slab-ocean model files) — no
  physics change in this tag alone.
- The tag in between, `cam6_2_021`, contains the real change: a substantial
  rework of aerosol convective transport and wet removal
  (`modal_aero_convproc.F90`, plus new namelist switches), a calendar bug fix
  specific to the NUOPC/ESMF driver (not applicable to this MCT-based build),
  and improved external-forcing file-checking.
- `cam6_2_021`'s own test log (in `doc/ChangeLog`) explicitly reports
  non-bit-for-bit differences against the prior baseline across a range of
  compsets, including general historical-forcing configurations similar to
  this project's — confirming the aerosol/convective change genuinely alters
  simulated answers by default, not just adding an opt-in switch.
- None of the five contrail-specific SourceMods files
  (`aircraft_emit.F90`, `ssatcontrail.F90`, `tracer_data.F90`, `physpkg.F90`,
  `horizontal_interpolate.F90`) appear in the `cam6_2_020`→`cam6_2_022` diff
  at all — the contrail scheme itself is untouched between the two tags.

Given the paper explicitly cites `cam6_2_022`, and the difference is real
(confirmed non-BFB) rather than cosmetic, this branch exists to match the
paper's stated code precisely, while the `cam6_2_020` branch remains intact
as the already-validated original setup.

## What's identical to the cam6_2_020 setup

- CESM base (`release-cesm2.1.3`), CIME override (`cime5.8.16` — confirmed
  compatible: `cam6_2_022`'s own `Externals_CAM.cfg` has no `[cime]` section
  at all, and the CIME-version-sensitive `cime_config/buildlib` script that
  originally required `cime5.8.16` is unchanged between the two CAM tags)
- The entire Levante machine port (`config_machines.xml`,
  `config_batch.xml`, `config_compilers.xml`) — captured in `patches/cime.patch`
  on this branch, identical in content to the corrected version on the
  `cam6_2_020` branch
- All CLM/CICE/MOSART/CISM source and `buildlib` patches — these components
  are pinned by the top-level `release-cesm2.1.3` `Externals.cfg`, unaffected
  by overriding just the `[cam]` entry
- Compset, grid, and the `CLM_FORCE_COLDSTART` fix for the `init_interp`
  runtime failure

## What's different: `cam6_2_022` requires additional optional externals

Building `cam6_2_022` failed at first with compile errors in
`clubb_intr.F90` (CAM) and `clmfates_paraminterfaceMod.F90` (CLM) — both
"error #7002: Error in opening the compiled module file," meaning the
underlying external library source was entirely absent, not just
misconfigured. Checking the working `cam6_2_020` sandbox confirmed these
same source directories (`components/cam/src/physics/clubb`,
`components/clm/src/fates`) *are* populated there, despite both tags marking
`required = True` for these externals in their respective `Externals_CAM.cfg`
/ `Externals_CLM.cfg` files.

The actual mechanism, confirmed via `checkout_externals --help`: **by
default, only the externals listed directly in the top-level
`Externals.cfg` are checked out — nested externals (those listed inside a
*sub*-project's own `Externals_CAM.cfg`/`Externals_CLM.cfg`, like `clubb`,
`silhs`, `atmos_phys`, `fates`) are treated as optional regardless of their
own internal `required` flag, unless targeted explicitly.** The `-o`
("also checkout optional externals") flag does *not* reach into nested
files either — each optional nested external must be fetched by name,
pointed at its own specific `Externals_*.cfg`:

```bash
cd components/cam
../../manage_externals/checkout_externals -e Externals_CAM.cfg -o clubb silhs atmos_phys

cd ../clm
../../manage_externals/checkout_externals -e Externals_CLM.cfg -o fates
```

Two further things worth knowing about this step:

1. **Order matters relative to source patches.** `checkout_externals`
   refuses to fetch anything (even unrelated externals) if it detects any
   repository already in a modified/"dirty" state — which our own CLM/CICE/
   MOSART/CISM source patches trigger immediately once applied. The fix
   sequence has to be: fetch everything (including these optional
   externals) *first*, patch afterward — not the reverse. If patches are
   already applied and this is hit, temporarily revert them
   (`git checkout -- .` in each affected component directory), fetch, then
   reapply.
2. **This same requirement almost certainly applied to the original
   `cam6_2_020` setup too** — the `clubb`/`fates` source is present there,
   meaning this same `-e ... -o ...` step (or an equivalent) must have been
   done at some point, but it wasn't captured in that branch's port log at
   the time. Worth treating the `cam6_2_020` branch's reproduction runbook
   as incomplete on this point until it's updated.

## A process lesson from this branch's setup: keep patches in sync with the live config

While reapplying the (at-the-time) saved `cime.patch` to this new checkout,
`case.setup` produced an `env_mach_specific.xml` with no `LD_LIBRARY_PATH`
entry at all — despite `git diff --stat` showing `config_machines.xml` as
changed. The saved patch had been exported early in the original session,
*before* the runtime-library fixes (`module purge`, `LD_LIBRARY_PATH`) were
made to the live `cam6_2_020` sandbox — and was never re-exported afterward.
The backup repository's `cam6_2_020` branch patch was, at the time this was
discovered, equally stale (fixed as part of the same cleanup that produced
this branch).

The practical lesson: **any time the live machine config is edited after an
initial patch export, the patch needs re-exporting** (`git diff` in the
live checkout, overwrite the saved `.patch` file) — a stale saved patch
looks identical at a glance (`git apply` succeeds silently either way) and
only surfaces as a problem much later, in a way that looks like a new bug
rather than an old, un-synced fix.

## Validation

Built successfully (`case.build`) and completed a 5-timestep smoke test
(`case.run` + `case.st_archive`, both `COMPLETED`/exit `0:0`), with a full,
consistent restart-file set for every component at the expected final
timestamp — the same validation standard applied to the `cam6_2_020` branch.
