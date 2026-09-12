"""Quantitative models behind the product's decisions.

Four places where the pipeline was using a guessed constant and where the problem
actually has a known mathematical structure:

  auction.py      What a signal is worth after accounting for who else can see it.
  tails.py        Portfolio construction when returns have infinite variance.
  information.py  Which candidate a human should look at next.

A fourth was planned — a sequential-decision model setting each stage's gate from
what later stages cost — and is deliberately not here. It needs measured per-stage
likelihood ratios to parameterise, and those need labelled data that does not exist
yet. Building it now would mean inventing its inputs, which is how a model ends up
looking authoritative while encoding a guess.

Every model here states its assumptions and has a test against a closed-form or
simulated result. A model whose assumptions are not stated is worse than an
honest guess, because it borrows authority it has not earned.
"""
