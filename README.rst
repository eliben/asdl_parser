Status - please read this first!
================================

This code has been submitted to upstream CPython in
`early 2014 <https://bugs.python.org/issue19655>`_. I keep the separate
repository alive mostly for historic interest and for folks who want to play
with real ASDL-based code generators in a simpler environment than the
CPython repository.

asdl_parser
===========

Standalone ASDL parser for upstream CPython 3.x.

The parser is in a single file - asdl.py; it contains a hand-written lexer and a
recursive-descent parser.

Note: Python.asdl (the ASDL definition file for Python) and asdl_c.py (emitter
for Python-ast.[hc]) are copied over from the CPython repository (default
branch); I applied some very small cleanups to asdl_c.py, mainly
because asdl.py produces cleaner ASTs than the old Spark-based parser. When run,
it produces exactly the same Python-ast.[hc] as in upstream CPython.

Python version
==============

The officially required version is Python 3.3, but should run with any 3.x

License
=======

Same as CPython: Python Software Foundation License (LICENSE file included
here).
