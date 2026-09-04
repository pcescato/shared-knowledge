---
title: "Choosing a Postgres isolation level for read-heavy APIs"
description: "How to pick a transaction isolation level when read consistency matters more than write contention."
category: "Databases"
tags:
  - postgres
  - transactions
  - isolation-levels
source: "community"
created_at: "2026-09-04"
---

## Problem

APIs backed by Postgres often read data that must be internally consistent within a
single request, without paying the cost of serializable transactions.

## Solution

Use `READ COMMITTED` for most endpoints and switch to `REPEATABLE READ` only for
transactions that need a stable snapshot across several queries.

## Caveats

`REPEATABLE READ` in Postgres can fail with serialization errors that the application
must retry.
