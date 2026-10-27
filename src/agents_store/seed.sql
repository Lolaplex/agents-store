-- Core vocabulary. Idempotent (INSERT OR IGNORE). Namespaced attrs are seeded by their wrappers.

INSERT OR IGNORE INTO attr (name, value_type, cardinality, doc) VALUES
  ('title',   'text',    'one',  'human title'),
  ('body',    'text',    'one',  'long-form text (markdown)'),
  ('when',    'instant', 'one',  'start instant, UTC ISO-8601 with Z'),
  ('end',     'instant', 'one',  'end instant, UTC ISO-8601 with Z'),
  ('status',  'text',    'one',  'task state: open | done'),
  ('md:path', 'text',    'many', 'markdown projection path relative to the folder root'),
  ('more:type',    'text',    'one',  'MORe event type'),
  ('more:actor',   'text',    'one',  'MORe event actor'),
  ('more:at',      'instant', 'one',  'MORe event timestamp (UTC ISO-8601 with Z)'),
  ('more:subject', 'ref',     'many', 'MORe subject that is a store entity (entity id)'),
  ('more:subject_ptr', 'text', 'many', 'MORe subject that is not a store entity: pointer target id (artifact id or external locator), never a copy'),
  ('more:pinned_against', 'text', 'many', 'MORe envelope pinned_against, verbatim: artifact@version, commit or baseline'),
  ('more:pin',     'text',    'many', 'version pin as entity@tx'),
  ('more:body',    'json',    'one',  'MORe type-specific body'),
  ('more:topic',   'text',    'one',  'MORe decision question / ADR topic');

INSERT OR IGNORE INTO kind (name, required, optional, derivations) VALUES
  ('event', '["when"]',   '["end","title"]',  '[{"attr":"end","from":["when"],"rule":"plus_1h"}]'),
  ('task',  '["status"]', '["when","title"]', '[]'),
  ('note',  '["body"]',   '["title"]',        '[]'),
  ('more-event', '["more:type","more:actor"]', '["more:at","more:subject","more:subject_ptr","more:pinned_against","more:pin","more:body"]', '[]'),
  ('decision', '["title","body","more:topic","more:pin"]', '["more:type","more:actor","more:at","more:subject","more:subject_ptr","more:pinned_against"]', '[]');
