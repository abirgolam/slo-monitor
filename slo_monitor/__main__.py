"""Entry point: python -m slo_monitor --config config.toml"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from . import __version__
from .config import ConfigError, load
from .metrics import serve
from .monitor import Monitor


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="slo-monitor", description=__doc__)
    p.add_argument("--config", default="config.toml")
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--version", action="version", version=__version__)
    args = p.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        cfg = load(args.config)
    except (ConfigError, FileNotFoundError) as e:
        logging.critical("invalid config: %s", e)
        return 2

    mon = Monitor(cfg)
    serve(mon.registry, mon.status, cfg.listen_port)
    logging.info("metrics on :%d/metrics, status on :%d/status", cfg.listen_port, cfg.listen_port)

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # clean stop for `docker stop`
    try:
        mon.run_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
