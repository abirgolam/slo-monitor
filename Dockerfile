FROM python:3.12-slim

# No pip install step: the monitor uses only the standard library, so there is no dependency supply chain.
WORKDIR /app
COPY slo_monitor/ slo_monitor/
COPY demo/ demo/
COPY config.toml .

# Don't run as root.
RUN useradd --system --uid 10001 monitor
USER monitor

EXPOSE 9105
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9105/healthz', timeout=2)"
ENTRYPOINT ["python", "-m", "slo_monitor"]
CMD ["--config", "config.toml"]
