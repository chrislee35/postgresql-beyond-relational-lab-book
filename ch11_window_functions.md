# Chapter 11 — Window Functions: Analytics Beyond `GROUP BY`

> *"`GROUP BY` answers a question by throwing away the rows that don't
> fit in the answer. A window function answers the same question and
> keeps every row anyway."*

---

## Background

If you've used `GROUP BY`, you already know the shape of the problem
this chapter solves — and the shape of its one real limitation.
`GROUP BY` answers "what's the average rating per neighbourhood?" by
collapsing every business in a neighbourhood down into a single output
row: you get the average, but every individual business that went into
computing it is gone from the result. Most of the time that's exactly
what you want. But plenty of real questions don't fit that shape: "how
does each business's rating compare to its neighbourhood's average,
*while still showing me every business*?" "What's this business's
running revenue total, quarter by quarter, without collapsing the
quarters together?" `GROUP BY` cannot answer either one — the instant it
groups, the individual rows that made up the group are gone for good.

A **window function** answers a `GROUP BY`-shaped question without
paying that price. It looks at a set of rows related to the current row
— its "window" — computes something over them, and attaches the result
to the current row, which survives, completely unchanged, right
alongside every other row. Nothing collapses. Start with 48 rows, end
with 48 rows, every one of them now carrying an answer that depended on
looking at some of its neighbours.

That's the single idea this entire chapter builds on, and it's worth
sitting with before touching any syntax:

> **`GROUP BY` reduces row count. A window function never does.**

### Four pieces, defined before you see them used

Every example below is built from four ingredients. Knowing what each
one means in plain language first should make the SQL read as sentences
instead of unfamiliar syntax:

| Piece | Plain-language meaning |
|-------|--------------------------|
| `OVER (...)` | "Compute this using a window of related rows, not just this one row." Attached after a function call — `AVG(x) OVER (...)` — it's what turns an ordinary aggregate into a window function. An empty `OVER ()` means "the window is every row in the result." |
| `PARTITION BY col` | "Only look at rows that share this row's value of `col`." The window equivalent of `GROUP BY` — it restricts *which rows count*, without collapsing any of them. |
| `ORDER BY col` *(written inside `OVER (...)`)* | "Put the rows in this order before computing." This ordering lives entirely inside the window — it's unrelated to the query's own outer `ORDER BY`, and the two are free to differ or even conflict. |
| frame clause — e.g. `ROWS BETWEEN 6 PRECEDING AND CURRENT ROW` | Out of the rows the partition and ordering make available, *exactly which ones* count toward this specific row's calculation. |

Exercise 1 walks through all four, one at a time, against a dataset
small enough to check by hand — five numbers, no Portsmith backstory
required, so the mechanics stay in view before any real data shows up.

---

## The Scenario

This chapter doesn't tell one Portsmith story — it reuses four different
tables to show that window functions are a general-purpose tool, not a
feature tied to any one kind of data:

| Object              | Source        | Used for                                             |
|----------------------|---------------|--------------------------------------------------------|
| `businesses`          | Chapter 1     | Ranking businesses within their own neighbourhood       |
| `sensor_readings`      | Chapter 8     | 7-day rolling averages and day-over-day change          |
| `network_events`       | Chapter 7     | Detecting login "sessions" via gaps and islands          |
| `business_revenue`      | *(new, this chapter)* | Running totals and percentage-of-category-total |

`business_revenue` is the one genuinely new thing here — a small,
synthetic quarterly revenue figure for each of the 48 businesses from
Chapter 1, built specifically so Exercise 6 has real running-total and
percentage-of-partition data to work with.

---

## Exercise Goals

By the end of this chapter you will be able to:

- Explain, without looking anything up, why `AVG(x) OVER ()` returns a
  value on every row while `AVG(x)` with `GROUP BY` returns one row —
  and predict, for any `OVER (...)` clause, exactly which rows are
  "in the window" for a given output row.
- Rank rows within groups with `RANK()` and `DENSE_RANK()`, and state
  precisely how the two disagree the moment there's a tie.
- Write an explicit frame clause to compute a rolling average, and
  explain why adding `ORDER BY` to a window — with no frame clause at
  all — silently changes the default frame.
- Use `LAG()`/`LEAD()` to compare a row to its neighbour without a
  self-join.
- Recognize the "gaps and islands" pattern and use it to turn a raw
  event stream into sessions.
- Combine two different `PARTITION BY` scopes — one for a running total,
  one for a percentage-of-total — in a single `SELECT`.

---

## Installation

Nothing to install. Window functions have been part of core PostgreSQL
since version 8.4 (2009) — no extension, no configuration.

---

## Loading the Data

This chapter needs Chapters 1, 7, and 8's data, plus one new small table:

```bash
python data/ch01_seed.py   # businesses
python data/ch07_seed.py   # network_events
python data/ch08_seed.py   # sensors, then run Chapter 8's own exercises
                            # through Exercise 2 to get sensor_readings populated
python data/ch11_seed.py   # business_revenue (new this chapter)
```

`business_revenue` only needs `businesses` to already exist — it doesn't
depend on Chapters 7 or 8 at all.

### Pin the session timezone

```sql
SET timezone = 'UTC';
```

Same reason as Chapter 8: Exercises 3 and 4 group `sensor_readings` by
`date_trunc('day', recorded_at)`, and a day boundary computed in any
timezone other than UTC quietly buckets a different set of 5-minute
readings into "Feb 1" than the ones this chapter's numbers were computed
from — not a rounding difference, a genuinely different average, since
each bucket ends up averaging different rows entirely. Run this at the
top of every session in this chapter, including the psql session that
runs the prerequisite check below, or Exercises 3 and 4's numbers won't
match what's printed here even though the query is identical.

### Verify the prerequisites

```sql
SELECT 'businesses' AS table, COUNT(*) FROM businesses
UNION ALL SELECT 'network_events', COUNT(*) FROM network_events
UNION ALL SELECT 'sensor_readings', COUNT(*) FROM sensor_readings
UNION ALL SELECT 'business_revenue', COUNT(*) FROM business_revenue;
```

```
       table       |  count
--------------------+---------
 businesses         |      48
 network_events      |     116
 sensor_readings     | 9648000
 business_revenue    |     192
(4 rows)
```

If all four match, proceed to the exercises.

---

## Exercises

---

### Exercise 1 — The Mental Model, Traced By Hand

Forget Portsmith for a moment. Here are five temperature readings from
one morning:

```sql
SELECT * FROM (VALUES
    ('06:00'::time, 52.1),
    ('07:00'::time, 53.4),
    ('08:00'::time, 55.8),
    ('09:00'::time, 58.2),
    ('10:00'::time, 60.5)
) AS t(reading_time, temp_f);
```

```
 reading_time | temp_f
--------------+--------
 06:00:00     |   52.1
 07:00:00     |   53.4
 08:00:00     |   55.8
 09:00:00     |   58.2
 10:00:00     |   60.5
(5 rows)
```

Five rows in, five rows to reason about. Keep this exact dataset in mind
for everything below.

**1.1 — `GROUP BY` collapses; `OVER ()` doesn't**

```sql
SELECT AVG(temp_f) FROM (VALUES
    ('06:00'::time, 52.1), ('07:00'::time, 53.4), ('08:00'::time, 55.8),
    ('09:00'::time, 58.2), ('10:00'::time, 60.5)
) AS t(reading_time, temp_f);
```

```
         avg
---------------------
 56.0000000000000000
(1 row)
```

Five rows go in, one number comes out. That's the `AVG(temp_f)` you
already know. Now the window version — same aggregate, same result, one
difference:

```sql
SELECT reading_time, temp_f,
       round(AVG(temp_f) OVER ()::numeric, 2) AS morning_avg
FROM (VALUES
    ('06:00'::time, 52.1), ('07:00'::time, 53.4), ('08:00'::time, 55.8),
    ('09:00'::time, 58.2), ('10:00'::time, 60.5)
) AS t(reading_time, temp_f);
```

```
 reading_time | temp_f | morning_avg
--------------+--------+-------------
 06:00:00     |   52.1 |       56.00
 07:00:00     |   53.4 |       56.00
 08:00:00     |   55.8 |       56.00
 09:00:00     |   58.2 |       56.00
 10:00:00     |   60.5 |       56.00
(5 rows)
```

Five rows go in, five rows come out — every one of them now carrying
`56.00`, the exact number `GROUP BY` gave you, just not at the cost of
the other four rows. An empty `OVER ()` means "the window is every row
here," so every row gets the same whole-set average stamped onto it.
This is the entire idea from the Background section, now sitting in
front of you as actual output: nothing collapsed.

**1.2 — The gotcha: adding `ORDER BY` silently changes the frame**

Now add one thing — `ORDER BY reading_time`, *inside* the `OVER (...)`:

```sql
SELECT reading_time, temp_f,
       round(AVG(temp_f) OVER (ORDER BY reading_time)::numeric, 2) AS running_avg
FROM (VALUES
    ('06:00'::time, 52.1), ('07:00'::time, 53.4), ('08:00'::time, 55.8),
    ('09:00'::time, 58.2), ('10:00'::time, 60.5)
) AS t(reading_time, temp_f);
```

```
 reading_time | temp_f | running_avg
--------------+--------+-------------
 06:00:00     |   52.1 |       52.10
 07:00:00     |   53.4 |       52.75
 08:00:00     |   55.8 |       53.77
 09:00:00     |   58.2 |       54.88
 10:00:00     |   60.5 |       56.00
(5 rows)
```

Same function, same data, completely different numbers — and only the
*last* row still shows `56.00`. This is the single most common surprise
in all of window functions, so it's worth tracing exactly what changed,
row by row:

| `reading_time` | `temp_f` | rows actually included in this row's window | `running_avg` |
|-----------------|----------|-----------------------------------------------|-----------------|
| 06:00 | 52.1 | `[06:00]` | 52.10 |
| 07:00 | 53.4 | `[06:00, 07:00]` | 52.75 |
| 08:00 | 55.8 | `[06:00, 07:00, 08:00]` | 53.77 |
| 09:00 | 58.2 | `[06:00, 07:00, 08:00, 09:00]` | 54.88 |
| 10:00 | 60.5 | `[06:00, 07:00, 08:00, 09:00, 10:00]` | 56.00 |

Adding `ORDER BY` to a window did not just sort the rows — it silently
changed *how many rows count* for each one, from "every row" down to
"every row up to and including this one." That's PostgreSQL's default
frame the moment a window has an `ORDER BY` and no explicit frame
clause: `RANGE UNBOUNDED PRECEDING AND CURRENT ROW`, i.e., a running
calculation. Without `ORDER BY`, there's nothing to run *up to*, so the
default frame is the whole partition instead, which is exactly what
1.1's flat `56.00` was. Nothing in the syntax announces this change —
`ORDER BY` looks like it should only affect display order, and inside a
window it affects something much bigger. Committing this one rule to
memory now will save you from debugging a "wrong" running total later
that was never actually wrong, just unexpectedly running.

<img src="imgs/ch11_frame_default.svg" alt="Two rows of boxes compared: with OVER() and no ORDER BY, every one of the five readings attaches the same flat value, 56.00, the whole-partition average; with OVER(ORDER BY reading_time), each reading attaches a different, growing value as the default frame silently switches from the whole partition to a running calculation up to and including the current row"/>

**1.3 — `PARTITION BY`: independent windows, still no collapsing**

Add a second sensor to the tiny dataset:

```sql
SELECT sensor_label, reading_time, temp_f,
       round(AVG(temp_f) OVER (PARTITION BY sensor_label ORDER BY reading_time)::numeric, 2) AS running_avg
FROM (VALUES
    ('Temp-01', '06:00'::time, 52.1), ('Temp-01', '07:00'::time, 53.4), ('Temp-01', '08:00'::time, 55.8),
    ('Temp-02', '06:00'::time, 48.9), ('Temp-02', '07:00'::time, 49.5), ('Temp-02', '08:00'::time, 50.1)
) AS t(sensor_label, reading_time, temp_f)
ORDER BY sensor_label, reading_time;
```

```
 sensor_label | reading_time | temp_f | running_avg
--------------+--------------+--------+-------------
 Temp-01      | 06:00:00     |   52.1 |       52.10
 Temp-01      | 07:00:00     |   53.4 |       52.75
 Temp-01      | 08:00:00     |   55.8 |       53.77
 Temp-02      | 06:00:00     |   48.9 |       48.90
 Temp-02      | 07:00:00     |   49.5 |       49.20
 Temp-02      | 08:00:00     |   50.1 |       49.50
```

`Temp-01`'s running average never sees `Temp-02`'s numbers, and vice
versa — `PARTITION BY` walled the two sensors off into completely
independent windows, the same way `GROUP BY sensor_label` would have,
except both sensors' six rows are all still here. This is `PARTITION BY`
doing to a window exactly what it would do to a `GROUP BY`: split the
data into groups — just without ever throwing a row away.

**1.4 — An explicit frame clause: precise control**

1.2's running average grows to include more and more history as it goes
— by the last row, it's averaging all five readings. A **rolling**
average instead asks "the last *N* readings only," which needs an
explicit frame clause instead of relying on the default:

```sql
SELECT reading_time, temp_f,
       round(AVG(temp_f) OVER (ORDER BY reading_time
                                ROWS BETWEEN 1 PRECEDING AND CURRENT ROW)::numeric, 2) AS rolling_2
FROM (VALUES
    ('06:00'::time, 52.1), ('07:00'::time, 53.4), ('08:00'::time, 55.8),
    ('09:00'::time, 58.2), ('10:00'::time, 60.5)
) AS t(reading_time, temp_f);
```

```
 reading_time | temp_f | rolling_2
--------------+--------+-----------
 06:00:00     |   52.1 |     52.10
 07:00:00     |   53.4 |     52.75
 08:00:00     |   55.8 |     54.60
 09:00:00     |   58.2 |     57.00
 10:00:00     |   60.5 |     59.35
```

| `reading_time` | rows in this row's window (`1 PRECEDING AND CURRENT ROW`) | `rolling_2` |
|-----------------|--------------------------------------------------------------|---------------|
| 06:00 | `[06:00]` — no prior row exists yet, so just itself | 52.10 |
| 07:00 | `[06:00, 07:00]` | 52.75 |
| 08:00 | `[07:00, 08:00]` | 54.60 |
| 09:00 | `[08:00, 09:00]` | 57.00 |
| 10:00 | `[09:00, 10:00]` | 59.35 |

<img src="imgs/ch11_frame_sliding.svg" alt="Three snapshots of the same five readings, each highlighting a different pair of boxes in green as the current row's window: for current row 07:00 the window covers 06:00-07:00, for 08:00 it covers 07:00-08:00, and for 09:00 it covers 08:00-09:00 — the two-box window sliding one step to the right each time, never including anything outside that pair"/>

The window is now a fixed-size sliding pair, not an ever-growing history
— `08:00`'s value depends on `07:00` and `08:00` only, never `06:00`.
`ROWS BETWEEN 1 PRECEDING AND CURRENT ROW` is deliberately the same
shape of clause Exercise 3 uses next, just with a smaller number: this
tiny example *is* a 2-reading rolling average, and Exercise 3 is nothing
more than this same idea with `6 PRECEDING` and real sensor data behind
it.

---

### Exercise 2 — Ranking Businesses Within Their Neighbourhood

**2.1 — `RANK()` and `DENSE_RANK()`, side by side**

```sql
SELECT name, neighbourhood, (details->>'rating')::numeric AS rating,
       RANK()       OVER (PARTITION BY neighbourhood ORDER BY (details->>'rating')::numeric DESC) AS rank,
       DENSE_RANK() OVER (PARTITION BY neighbourhood ORDER BY (details->>'rating')::numeric DESC) AS dense_rank
FROM   businesses
WHERE  neighbourhood IN ('Harbour District', 'Riverside')
ORDER  BY neighbourhood, rating DESC;
```

```
            name             |  neighbourhood   | rating | rank | dense_rank
------------------------------+------------------+--------+------+------------
 Lighthouse Bookshop          | Harbour District |    5.0 |    1 |          1
 Portsmith Fish Market        | Harbour District |    4.8 |    2 |          2
 Saltbox Gallery              | Harbour District |    4.7 |    3 |          3
 Mariners Rest B&B            | Harbour District |    4.7 |    3 |          3
 Harbour View Theater         | Harbour District |    4.6 |    5 |          4
 Tidal Wave Surf Shop         | Harbour District |    4.5 |    6 |          5
 The Gilded Clam              | Harbour District |    4.5 |    6 |          5
 Harbour Inn                  | Harbour District |    4.3 |    8 |          6
 Anchor & Oar Tavern          | Harbour District |    4.1 |    9 |          7
 River Bend Bakery            | Riverside        |    4.8 |    1 |          1
 Portsmith Veterinary Clinic  | Riverside        |    4.8 |    1 |          1
 Dr. Chen Dentistry           | Riverside        |    4.7 |    3 |          2
 Quay Street Deli             | Riverside        |    4.6 |    4 |          3
 The Art Depot                | Riverside        |    4.6 |    4 |          3
 Thai Orchid                  | Riverside        |    4.5 |    6 |          4
 The Riverside Vegan          | Riverside        |    4.5 |    6 |          4
 Riverside Cinema             | Riverside        |    4.4 |    8 |          5
 Portsmith Pharmacy           | Riverside        |    4.3 |    9 |          6
(18 rows)
```

(`Lighthouse Bookshop`'s `5.0` is Chapter 1, Exercise 5's `jsonb_set`
update — if you're seeing `4.9` instead, that exercise hasn't run yet in
this database, which is fine; the ranking logic below is identical
either way.)

**2.2 — Reading the tie exactly**

Look at Harbour District's two businesses tied at `4.7`: both get
`rank = 3`. The next business down, at `4.6`, gets `rank = 5` under
`RANK()` — `4` is simply never used, because two rows already claimed
"3rd place" and `RANK()` counts every row ahead of you, ties included.
`DENSE_RANK()` disagrees on principle: it counts *distinct rating
values* seen so far, so `4.6` is the 4th distinct value in the list and
gets `dense_rank = 4`, no gap. Neither is "more correct" — `RANK()`
answers "how many businesses rate at or above me," `DENSE_RANK()`
answers "how many distinct rating tiers are at or above me" — but they
give a different answer to "who's in 4th place" the moment any tie
exists, and Riverside's `4.8` tie two rows later shows the same split
happening again.

---

### Exercise 3 — A 7-Day Rolling Average on `sensor_readings`

**3.1 — Aggregate to daily first**

`sensor_readings` reports every five minutes — a rolling average over
raw readings would be a rolling average of noise. Roll up to one row per
day first, the same shape of query Chapter 9 turned into a materialized
view, just computed directly here instead:

```sql
WITH daily AS (
    SELECT date_trunc('day', recorded_at)::date AS reading_day,
           round(AVG(reading_value)::numeric, 2) AS daily_avg
    FROM   sensor_readings
    WHERE  sensor_id = 1
    AND    recorded_at >= '2024-02-01' AND recorded_at < '2024-02-15'
    GROUP  BY 1
)
SELECT * FROM daily ORDER BY reading_day;
```

```
 reading_day | daily_avg
-------------+-----------
 2024-02-01  |     42.46
 2024-02-02  |     42.37
 2024-02-03  |     42.37
 2024-02-04  |     42.40
 2024-02-05  |     42.32
 2024-02-06  |     42.43
 2024-02-07  |     42.43
 2024-02-08  |     42.38
 2024-02-09  |     42.29
 2024-02-10  |     42.40
 2024-02-11  |     42.45
 2024-02-12  |     42.48
 2024-02-13  |     42.40
 2024-02-14  |     42.41
(14 rows)
```

Sensor 1 over the first two weeks of February — the month right after
Chapter 8's dropped January partition, well clear of it. Check `sensors`
and this is genuinely `Temp-01`, the same sensor Exercise 1.3's toy
example was named after — the tiny hand-crafted dataset was standing in
for exactly this real one.

**3.2 — Layer the rolling average on top**

```sql
WITH daily AS (
    SELECT date_trunc('day', recorded_at)::date AS reading_day,
           round(AVG(reading_value)::numeric, 2) AS daily_avg
    FROM   sensor_readings
    WHERE  sensor_id = 1
    AND    recorded_at >= '2024-02-01' AND recorded_at < '2024-02-15'
    GROUP  BY 1
)
SELECT reading_day, daily_avg,
       round(AVG(daily_avg) OVER (ORDER BY reading_day
                                   ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)::numeric, 2) AS rolling_7day_avg
FROM   daily
ORDER  BY reading_day;
```

```
 reading_day | daily_avg | rolling_7day_avg
-------------+-----------+-------------------
 2024-02-01  |     42.46 |             42.46
 2024-02-02  |     42.37 |             42.42
 2024-02-03  |     42.37 |             42.40
 2024-02-04  |     42.40 |             42.40
 2024-02-05  |     42.32 |             42.38
 2024-02-06  |     42.43 |             42.39
 2024-02-07  |     42.43 |             42.40
 2024-02-08  |     42.38 |             42.39
 2024-02-09  |     42.29 |             42.37
 2024-02-10  |     42.40 |             42.38
 2024-02-11  |     42.45 |             42.39
 2024-02-12  |     42.48 |             42.41
 2024-02-13  |     42.40 |             42.40
 2024-02-14  |     42.41 |             42.40
(14 rows)
```

`6 PRECEDING AND CURRENT ROW` is 7 rows total — the exact same shape as
Exercise 1.4's `1 PRECEDING AND CURRENT ROW`, just sized for a week
instead of a pair. Watch the first week build up exactly like 1.4's
first row did: Feb 1 has no prior days, so its "7-day" average is really
a 1-day average; Feb 2 averages 2 days; the window doesn't reach a true
7 full days until Feb 7. `ROWS BETWEEN ... PRECEDING` never errors when
fewer rows exist than requested — it just uses whatever's actually
available, which is worth knowing before trusting the first few values
of any rolling window on real data.

---

### Exercise 4 — `LAG()`/`LEAD()`: Comparing a Row to Its Neighbour

**4.1 — Day-over-day change, without a self-join**

```sql
WITH daily AS (
    SELECT date_trunc('day', recorded_at)::date AS reading_day,
           round(AVG(reading_value)::numeric, 2) AS daily_avg
    FROM   sensor_readings
    WHERE  sensor_id = 1
    AND    recorded_at >= '2024-02-01' AND recorded_at < '2024-02-15'
    GROUP  BY 1
)
SELECT reading_day, daily_avg,
       LAG(daily_avg) OVER (ORDER BY reading_day) AS prev_day_avg,
       round((daily_avg - LAG(daily_avg) OVER (ORDER BY reading_day))::numeric, 2) AS day_over_day_change,
       LEAD(daily_avg) OVER (ORDER BY reading_day) AS next_day_avg
FROM   daily
ORDER  BY reading_day
LIMIT  6;
```

```
 reading_day | daily_avg | prev_day_avg | day_over_day_change | next_day_avg
-------------+-----------+--------------+----------------------+---------------
 2024-02-01  |     42.46 |              |                      |         42.37
 2024-02-02  |     42.37 |        42.46 |                -0.09 |         42.37
 2024-02-03  |     42.37 |        42.37 |                 0.00 |         42.40
 2024-02-04  |     42.40 |        42.37 |                 0.03 |         42.32
 2024-02-05  |     42.32 |        42.40 |                -0.08 |         42.43
 2024-02-06  |     42.43 |        42.32 |                 0.11 |         42.43
(6 rows)
```

`LAG(col)` reaches one row backward in the window's order; `LEAD(col)`
reaches one row forward. Both are just `AVG(...) OVER (...)`'s siblings
— ordinary window functions, not aggregates, so they don't need a frame
clause at all. February 1st has no prior day, so `prev_day_avg` and
`day_over_day_change` are both `NULL` for it — not zero, not an error,
genuinely unknown, exactly the way a self-join against "yesterday" would
also come up empty for the very first row. Before this chapter, the only
way to compare a row to its neighbour was a self-join on
`date - 1 = date`; `LAG()`/`LEAD()` is that same comparison with no join
at all.

---

### Exercise 5 — Gaps and Islands: Detecting Sessions in `network_events`

**5.1 — The pattern, in words before SQL**

"Gaps and islands" names a specific two-step trick: find the *gaps*
(where consecutive rows, for the same actor, are far enough apart in
time to count as separate events), then turn the space between gaps into
*islands* (contiguous runs, numbered, that become your sessions). Step
one is `LAG()` from Exercise 4. Step two is a cumulative `SUM()` — a
running total of "did a new island start yet," which is exactly
Exercise 1.2's running-total behavior, repurposed as a counter instead
of an average.

**5.2 — Step one: flag where each session starts**

```sql
SELECT source_ip, event_type, occurred_at,
       (occurred_at - LAG(occurred_at) OVER (PARTITION BY source_ip ORDER BY occurred_at))
         > interval '5 minutes' AS is_new_session
FROM   network_events
WHERE  source_ip IN ('192.0.2.47', '192.0.2.151')
ORDER  BY source_ip, occurred_at;
```

```
  source_ip  | event_type |      occurred_at       | is_new_session
-------------+------------+-------------------------+-----------------
 192.0.2.47  | api_call   | 2024-03-10 00:18:00-05 |
 192.0.2.47  | api_call   | 2024-03-10 00:20:00-05 | f
 192.0.2.47  | api_call   | 2024-03-10 00:28:00-05 | t
 192.0.2.47  | api_call   | 2024-03-10 00:36:00-05 | t
 192.0.2.47  | api_call   | 2024-03-10 00:38:00-05 | f
 192.0.2.151 | api_call   | 2024-03-09 23:53:00-05 |
 192.0.2.151 | api_call   | 2024-03-09 23:55:00-05 | f
 192.0.2.151 | api_call   | 2024-03-09 23:56:00-05 | f
 192.0.2.151 | api_error  | 2024-03-10 00:00:00-05 | f
 192.0.2.151 | api_call   | 2024-03-10 00:07:00-05 | t
 192.0.2.151 | api_call   | 2024-03-10 00:12:00-05 | f
```

A 5-minute threshold: `192.0.2.47`'s second event lands 2 minutes after
its first (`f`, still the same visit), but its third lands 8 minutes
after that (`t` — long enough to count as a new visit). The first row
for any IP has nothing before it, so `LAG()` returns `NULL` and the
comparison is `NULL`, not `true` or `false` — handled explicitly in the
next step.

**5.3 — Step two: turn the flags into session numbers**

```sql
WITH gapped AS (
    SELECT source_ip, event_type, occurred_at,
           (occurred_at - LAG(occurred_at) OVER (PARTITION BY source_ip ORDER BY occurred_at))
             > interval '5 minutes' AS is_new_session
    FROM   network_events
),
islands AS (
    SELECT source_ip, event_type, occurred_at,
           SUM(CASE WHEN is_new_session IS NOT FALSE THEN 1 ELSE 0 END)
             OVER (PARTITION BY source_ip ORDER BY occurred_at) AS session_num
    FROM   gapped
)
SELECT source_ip, session_num, event_type, occurred_at
FROM   islands
WHERE  source_ip IN ('192.0.2.47', '192.0.2.151')
ORDER  BY source_ip, occurred_at;
```

```
  source_ip  | session_num | event_type |      occurred_at
-------------+-------------+------------+-------------------------
 192.0.2.47  |           1 | api_call   | 2024-03-10 00:18:00-05
 192.0.2.47  |           1 | api_call   | 2024-03-10 00:20:00-05
 192.0.2.47  |           2 | api_call   | 2024-03-10 00:28:00-05
 192.0.2.47  |           3 | api_call   | 2024-03-10 00:36:00-05
 192.0.2.47  |           3 | api_call   | 2024-03-10 00:38:00-05
 192.0.2.151 |           1 | api_call   | 2024-03-09 23:53:00-05
 192.0.2.151 |           1 | api_call   | 2024-03-09 23:55:00-05
 192.0.2.151 |           1 | api_call   | 2024-03-09 23:56:00-05
 192.0.2.151 |           1 | api_error  | 2024-03-10 00:00:00-05
 192.0.2.151 |           2 | api_call   | 2024-03-10 00:07:00-05
 192.0.2.151 |           2 | api_call   | 2024-03-10 00:12:00-05
```

`IS NOT FALSE` — not `= true` — is what makes a row's own first event
(where `is_new_session` is `NULL`) correctly count as the start of
session 1 instead of silently vanishing from every sum downstream;
`NULL = true` and `NULL AND anything` are both `NULL` in SQL's
three-valued logic, never `true`, so a plain `WHEN is_new_session THEN
1` would skip every partition's opening row. `192.0.2.47` splits into
three short sessions; `192.0.2.151` splits into two. Neither IP did
anything unusual — the same `api_call`s, just separated by an 8- and a
7-minute pause respectively, long enough to cross this query's 5-minute
line.

**5.4 — Roll it up**

```sql
WITH gapped AS (
    SELECT source_ip, occurred_at,
           (occurred_at - LAG(occurred_at) OVER (PARTITION BY source_ip ORDER BY occurred_at))
             > interval '5 minutes' AS is_new_session
    FROM   network_events
),
islands AS (
    SELECT source_ip, occurred_at,
           SUM(CASE WHEN is_new_session IS NOT FALSE THEN 1 ELSE 0 END)
             OVER (PARTITION BY source_ip ORDER BY occurred_at) AS session_num
    FROM   gapped
)
SELECT COUNT(DISTINCT source_ip)            AS distinct_ips,
       COUNT(DISTINCT (source_ip, session_num)) AS total_sessions
FROM   islands;
```

```
 distinct_ips | total_sessions
--------------+-----------------
           51 |             66
(1 row)
```

51 distinct IPs produced 66 sessions — 15 of them split into more than
one visit under this threshold. Change `interval '5 minutes'` to
`interval '10 minutes'` (the longest gap that exists anywhere in this
dataset, per Chapter 7's generator) and every one of those 66 collapses
back down to exactly 51: the threshold you choose *is* the definition of
"one visit," and this query has no way of knowing which threshold is
right for your actual users — that's a judgment call the data alone
can't make for you.

---

### Exercise 6 — Running Total and Percentage-of-Category-Total, Together

**6.1 — Two different partitions, one query**

```sql
WITH revenue_calc AS (
    SELECT b.id, b.name, b.details->>'category' AS category, r.quarter, r.revenue,
           round(SUM(r.revenue) OVER (PARTITION BY r.business_id ORDER BY r.quarter
                                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)::numeric, 2)
             AS running_total,
           round(SUM(r.revenue) OVER (PARTITION BY b.id) * 100.0
                 / SUM(r.revenue) OVER (PARTITION BY b.details->>'category'), 2)
             AS pct_of_category_annual
    FROM   business_revenue r
    JOIN   businesses b ON b.id = r.business_id
)
SELECT name, quarter, revenue, running_total, pct_of_category_annual
FROM   revenue_calc
WHERE  name IN ('The Gilded Clam', 'Bella Napoli')
ORDER  BY name, quarter;
```

```
      name       | quarter | revenue  | running_total | pct_of_category_annual
------------------+---------+----------+----------------+--------------------------
 Bella Napoli     |       1 | 68827.50 |      68827.50 |                    7.35
 Bella Napoli     |       2 | 84983.85 |     153811.35 |                    7.35
 Bella Napoli     |       3 | 90452.38 |     244263.73 |                    7.35
 Bella Napoli     |       4 | 75346.83 |     319610.56 |                    7.35
 The Gilded Clam  |       1 | 75282.75 |      75282.75 |                    8.04
 The Gilded Clam  |       2 | 92954.38 |     168237.13 |                    8.04
 The Gilded Clam  |       3 | 98935.80 |     267172.93 |                    8.04
 The Gilded Clam  |       4 | 82413.52 |     349586.45 |                    8.04
```

Three window functions, two different `PARTITION BY` scopes, in the
exact same `SELECT`. `running_total` partitions by `business_id` and
orders by `quarter` — Exercise 1.2's running sum, applied to money
instead of temperature. `pct_of_category_annual` partitions by
`category` with **no `ORDER BY` at all** — Exercise 1.1's flat,
whole-partition total, computed twice with two different partitions
(once for just this business, once for its whole category) and divided.
Both restaurants' percentages stay identical across all four of their
own rows, exactly like 1.1's `56.00` did, because neither has an
`ORDER BY` to turn it into anything running.

**6.2 — A gotcha worth hitting on purpose**

Restrict the query further, to see what a narrower `WHERE` clause does
to a percentage that's supposed to mean "share of the whole category":

```sql
SELECT b.name, r.quarter, r.revenue,
       round(SUM(r.revenue) OVER (PARTITION BY b.id) * 100.0
             / SUM(r.revenue) OVER (PARTITION BY b.details->>'category'), 2) AS pct_of_category
FROM   business_revenue r
JOIN   businesses b ON b.id = r.business_id
WHERE  b.name IN ('The Gilded Clam', 'Bella Napoli')   -- filtered BEFORE the window runs
ORDER  BY b.name, r.quarter;
```

```
      name       | quarter | revenue  | pct_of_category
------------------+---------+----------+-------------------
 Bella Napoli     |       1 | 68827.50 |             47.76
 Bella Napoli     |       2 | 84983.85 |             47.76
 Bella Napoli     |       3 | 90452.38 |             47.76
 Bella Napoli     |       4 | 75346.83 |             47.76
 The Gilded Clam  |       1 | 75282.75 |             52.24
 The Gilded Clam  |       2 | 92954.38 |             52.24
 The Gilded Clam  |       3 | 98935.80 |             52.24
 The Gilded Clam  |       4 | 82413.52 |             52.24
```

`47.76 + 52.24 = 100.00` — these two restaurants apparently make up the
*entire* restaurant category, when Portsmith actually has 15. `WHERE`
runs before `OVER (...)` ever sees a row: filtering down to two
businesses filtered the `PARTITION BY category` window down to just
those same two businesses, so "the category total" silently became "the
total of the two rows I happened to ask for." The fix is 6.1's
structure, not a different formula: compute every window function
first, across the *entire* unfiltered table, inside a CTE — then filter
the CTE's output afterward, in an outer query the windows never see. A
`WHERE` clause placed before a window and a `WHERE` clause placed after
one are answering two different questions, and PostgreSQL will never
warn you which one you actually wrote.

---

## Summary — What You Should Now Know

| Tool | What it does |
|------|---------------|
| `func(...) OVER (...)` | Computes across a window of related rows without collapsing the current row away |
| `PARTITION BY col` | Restricts the window to rows sharing this row's value — `GROUP BY` without the collapsing |
| `ORDER BY col` inside `OVER (...)` | Orders the window — and, with no explicit frame, silently switches the default frame from "whole partition" to "running up to this row" |
| `ROWS BETWEEN x PRECEDING AND CURRENT ROW` | An explicit frame — precise, fixed-size control over which neighbouring rows count |
| `RANK()` vs. `DENSE_RANK()` | Agree with no ties; `RANK()` leaves gaps after a tie, `DENSE_RANK()` never does |
| `LAG()` / `LEAD()` | Reach one row backward/forward in window order — a neighbour comparison with no self-join |
| gaps and islands | `LAG()` flags where a new group starts; a cumulative `SUM()` turns those flags into group numbers |
| `IS NOT FALSE` | The three-valued-logic-safe way to treat a `NULL` flag (a partition's first row) as "start a new group" |
| Two `PARTITION BY` scopes, one query | Perfectly legal — e.g. a running total per entity alongside a percentage of a *different*, broader group |
| `WHERE` before `OVER (...)` | Filters the rows a window function ever sees — a narrow `WHERE` silently narrows what "the partition total" means |

**The key design insight** from this chapter is the one from the very
first paragraph, now proven six different ways: a window function is
what you reach for the moment a `GROUP BY`-shaped question needs an
answer *without* losing the rows that produced it. Ranking within a
group, a rolling average, a neighbour comparison, a session boundary, a
running total next to a category share — every one of these is the same
underlying move, `OVER (...)` attached to a function that would
otherwise collapse your data, with `PARTITION BY`, `ORDER BY`, and a
frame clause as the three knobs that decide exactly which neighbouring
rows a given row is allowed to see.

---

*Going further: Chapter 9's materialized views precompute the exact
kind of daily rollup Exercise 3 built on the fly — worth comparing
directly now that you've seen both: a materialized view pays the
aggregation cost once, at refresh time, while a window function pays it
on every query but never goes stale. Chapter 20's `pg_stat_statements`
work benefits from the running-total pattern in Exercise 6 when tracking
cumulative query cost over time. And Chapter 12's recursive CTEs are
this book's other tool for "a query that needs to see more than just the
current row" — recursive CTEs walk relationships the data itself defines
(a parent, a neighbour node), where window functions walk an *ordering*
you impose yourself; knowing which kind of "related rows" a problem
actually has is most of the work of picking the right one.*
