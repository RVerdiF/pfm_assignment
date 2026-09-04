"""Methodology and limitations page (walkthrough section).

Card 1 establishes this page as a destination in the navigation skeleton. The
final narrative — methodology, results interpretation, limitations and
recommendations — is completed by the walkthrough build-out card.
"""
from __future__ import annotations

import streamlit as st

from sections._components import placeholder_section


def render() -> None:
    placeholder_section(
        "Methodology and limitations",
        "This page will walk an evaluator through the attribution method "
        "(exact click-identifier matching, no fuzzy rules), the observed "
        "coverage and where conversions are lost, the sample's limitations "
        "(small sample, limited PostHog window, no authoritative daily "
        "commission source), and recommendations to improve coverage.",
    )
