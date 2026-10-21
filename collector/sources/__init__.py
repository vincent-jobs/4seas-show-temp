from . import airgradient, eight_sleep, heart_rate

# Add a module exposing async run(store) here to register another source type.
COLLECTORS = (heart_rate, airgradient, eight_sleep)
