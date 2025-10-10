#!/usr/bin/env bash
export ENV=dev
export DATA_SYMBOL=${DATA_SYMBOL:-SPY}
export MAX_DRAWDOWN_PCT=${MAX_DRAWDOWN_PCT:-20}
tal orchestrate --config config/base.yaml
