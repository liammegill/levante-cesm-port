# Levante CESM Port — Index

This repository holds machine-port patches and build logs for getting
CESM/CAM running on DKRZ Levante, organized by the specific upstream
CESM/CIME/CAM version combination each was built against. Each version
lives on its own branch (not merged into this one), since they're
independent efforts against frozen, unrelated upstream tags.

## Available ports

- [`cesm2.1.3-cime5.8.16-cam6_2_020`](../../tree/cesm2.1.3-cime5.8.16-cam6_2_020) —
  CESM2/CAM6.2, built for the Gettelman et al. (2021) COVID-contrail
  replication. CESM base `release-cesm2.1.3`, CIME overridden to
  `cime5.8.16`, CAM overridden to `cam6_2_020`. See
  `LEVANTE_PORT_LOG.md` on that branch for the full account.

- [`cesm2.1.3-cime5.8.16-cam6_2_022`](../../tree/cesm2.1.3-cime5.8.16-cam6_2_022) —
  Same CESM2/CAM6.2 replication, but built against `cam6_2_022` specifically
  to match the exact CAM tag the Gettelman et al. (2021) paper cites in its
  code-availability statement. See `CAM6_2_022_DELTA_LOG.md` on that branch
  for what differs from the `cam6_2_020` setup.

(add new entries here as new version ports are added)
