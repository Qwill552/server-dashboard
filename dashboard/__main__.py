"""Run the dashboard on localhost behind the existing Caddy proxy."""

import os
import threading

from .metrics import MetricsSampler
from .web import serve


def main() -> None:
    sampler = MetricsSampler()
    sampler.sample()
    threading.Thread(target=sampler.run_forever, daemon=True, name="metrics-sampler").start()
    serve(sampler, host="127.0.0.1", port=int(os.environ.get("DASHBOARD_PORT", "5100")))


if __name__ == "__main__":
    main()
