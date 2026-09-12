"""Quantitative models behind the product's decisions.

Four places where the pipeline was using a guessed constant and where the problem
actually has a known mathematical structure:

  auction.py      What a signal is worth after accounting for who else can see it.
  cascade.py      Where to set each stage's gate, given what later stages cost.
  tails.py        Portfolio construction when returns have infinite variance.
  information.py  Which candidate a human should look at next.

Every model here states its assumptions and has a test against a closed-form or
simulated result. A model whose assumptions are not stated is worse than an
honest guess, because it borrows authority it has not earned.
"""
