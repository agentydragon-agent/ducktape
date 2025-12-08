local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Snapshot lookups by slug use .filter_by(slug=...).one() or .filter_by(slug=...).first(), but slug is the primary key (see models.py line 153). SQLAlchemy's .get() method should be used for primary key lookups as it's more efficient and clearer: session.get(Snapshot, slug_value).
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/props/prompt_optimizer.py': [225]},
      note: 'Uses .filter_by(slug=...).first() for PK lookup',
      expect_caught_from: [['adgn/src/adgn/props/prompt_optimizer.py']],
    },
    {
      files: {'adgn/src/adgn/props/db/sync_specimens.py': [101]},
      note: 'Uses .filter_by(slug=...).one() for PK lookup',
      expect_caught_from: [['adgn/src/adgn/props/db/sync_specimens.py']],
    },
    {
      files: {'adgn/src/adgn/props/db/sync_specimens.py': [118]},
      note: 'Uses .filter_by(slug=...).one() for PK lookup',
      expect_caught_from: [['adgn/src/adgn/props/db/sync_specimens.py']],
    },
  ],
)
