"""Fixed-behaviour mock connectors for backlog ENG-04.

Each mock models exactly one SA/SD capability shape -- synchronous
timeslot booking, nightly-inventory PMS, and asynchronous channel
publication -- with fixed test data and deterministic failure modes
(connectors/fixtures.py). None of them perform network I/O or read any
credential; see specs/connector/README.md §3 for the scope statement that
this is a design-time boundary, not something these tests alone prove at
runtime.
"""
