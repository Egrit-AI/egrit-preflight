# Vendor target profile fixtures

Synthetic test data for the companion record in
[docs/vendor-target-profile.md](../../../docs/vendor-target-profile.md). The vendor, products, revisions, versions and
URLs are made up; the URLs use the reserved `.example` domain. Nothing here describes a real product, was read from a
vendor page or a device, or is a report.

- `valid/`: profiles a reader must accept. The file name says which case it is: a complete declared profile, a missing
  software revision, contradictory sources, a wrong architecture, an absent ABI, statements about another revision
  only, a sibling product with nothing stated, a later software revision, an equivalence scoped to two facts, and
  statements graded `observed`.
- `invalid/`: the complete profile with one thing broken, or text that is not a profile. A reader must reject each as
  a whole. The file name says what is wrong.

Do not edit these by hand. Run `python3 -m tests.make_profile_fixtures` from the repository root and review the diff;
`tests/test_profile.py` fails if they are stale.
