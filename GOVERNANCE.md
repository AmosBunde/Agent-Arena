# Governance

Agent Arena is maintained by a small group of maintainers who share
responsibility for reviews, releases, and the architecture decision record.

## Roles

- **Contributors**: anyone who opens issues or pull requests. The
  contribution process is documented in
  [docs/guides/contributing.md](docs/guides/contributing.md).
- **Maintainers**: contributors with merge rights. Maintainers review pull
  requests, steward the ADRs, cut releases, and hold the security contact.

The current maintainer list is the CITATION.cff author list.

## Becoming a maintainer

1. A track record: several merged contributions of substance across more
   than one area of the codebase, and review participation that shows care
   for the ADRs and the stability policy.
2. Nomination by an existing maintainer in a public issue.
3. Consensus of the existing maintainers within two weeks; silence is not
   consent. One sustained objection blocks, with reasons stated in the
   issue.
4. On acceptance: repository write access, addition to CITATION.cff, and a
   note in the CHANGELOG of the next release.

## Stepping down and removal

Maintainers may step down at any time by opening an issue. A maintainer
inactive for twelve months is asked whether they wish to remain; no answer
within a month means emeritus status (listed, no merge rights). Removal for
cause requires consensus of the other maintainers.

## Decision making

Day to day decisions happen in issues and pull requests. Architectural
decisions go through the ADR process
([docs/guides/contributing.md](docs/guides/contributing.md), ADR amendment
process); breaking changes additionally follow
[docs/STABILITY.md](docs/STABILITY.md). When maintainers disagree and
discussion stalls, the ADR records the options and the majority decision,
including the dissent.

## Releases

Any maintainer may cut a release following the cadence in the contributing
guide. The v1.0 stability guarantee binds all releases from the v1.0.0 tag
onward.
