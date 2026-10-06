-- Core vocabulary. Idempotent (INSERT OR IGNORE). Namespaced attrs are seeded by their wrappers.

INSERT OR IGNORE INTO attr (name, value_type, cardinality, doc) VALUES
  ('title',   'text',    'one',  'human title'),
  ('body',    'text',    'one',  'long-form text (markdown)'),
  ('when',    'instant', 'one',  'start instant, UTC ISO-8601 with Z'),
  ('end',     'instant', 'one',  'end instant, UTC ISO-8601 with Z'),
  ('status',  'text',    'one',  'task state: open | done'),
  ('md:path', 'text',    'many', 'markdown projection path relative to the folder root');

INSERT OR IGNORE INTO kind (name, required, optional, derivations) VALUES
  ('event', '["when"]',   '["end","title"]',  '[{"attr":"end","from":["when"],"rule":"plus_1h"}]'),
  ('task',  '["status"]', '["when","title"]', '[]'),
  ('note',  '["body"]',   '["title"]',        '[]');
