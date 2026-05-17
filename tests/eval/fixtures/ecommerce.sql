CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    total REAL NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO customers (id, name, country) VALUES
    (1, 'Ana', 'ES'),
    (2, 'Luis', 'ES'),
    (3, 'Mike', 'US'),
    (4, 'Sara', 'US'),
    (5, 'Hans', 'DE');

INSERT INTO orders (id, customer_id, total, created_at) VALUES
    (1, 1, 19.99, '2026-01-10'),
    (2, 2, 49.50, '2026-01-12'),
    (3, 1, 12.00, '2026-02-01'),
    (4, 3, 99.00, '2026-02-15'),
    (5, 4, 5.00,  '2026-03-01')
