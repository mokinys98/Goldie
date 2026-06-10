# Configuration contract

Configurations are immutable JSON documents stored in PostgreSQL.

Lifecycle:

```text
DRAFT -> VALIDATED -> ACTIVE -> SUPERSEDED
```

Activation supersedes the previous active version and starts a new `Run`.
Editing an active config creates another draft. YAML is only an interchange
format and never an active source.

Required sections: market, strategy, filters, session, and theoretical trade.
All point-based values are interpreted using the broker symbol specification.

