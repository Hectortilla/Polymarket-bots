# C4 model rules

Use this reference to select diagram types and audit semantic correctness. The
official C4 model is notation- and tooling-independent.

Primary sources:

- [C4 model overview](https://c4model.com/)
- [Diagram types](https://c4model.com/diagrams)
- [Notation guidance](https://c4model.com/diagrams/notation)
- [Architecture diagram review checklist](https://c4model.com/diagrams/checklist)

## Abstractions

| Abstraction | Meaning | Common modelling error |
|---|---|---|
| Person | A human role or persona that uses or interacts with a software system. | Modelling individual named users instead of roles. |
| Software system | The highest-level software abstraction that delivers value to people or other systems. | Treating every service or repository as a separate system. |
| Container | A separately runnable/deployable application or a data store inside a software system. | Equating it with a Docker container, module, package, or directory. |
| Component | A cohesive set of implementation responsibilities behind an interface within one container. | Treating every class or file as a component. |
| Code element | An implementation-level construct inside one component. | Maintaining volatile class diagrams without a clear need. |

Libraries normally belong inside the container that executes them. Model a
shared library as a component only when doing so makes a selected container view
clearer; do not model it as a runtime container.

## Diagram selection

| View | Scope | Primary contents | Default use |
|---|---|---|---|
| System landscape | Organization, portfolio, or domain | People and software systems | Use for several related systems without one focal system. |
| System context | One software system | Focal system, people, directly connected external systems | Create for almost every whole-system task. |
| Container | One software system | Its applications/data stores and directly connected actors/systems | Create for almost every whole-system task. |
| Component | One container | Its components and directly connected supporting elements | Create only where added detail has durable value. |
| Code | One component | Classes, functions, schemas, or equivalent code constructs | Prefer on-demand generation; avoid as long-lived documentation. |
| Dynamic | One use case or runtime scenario | Ordered interactions among elements from the static model | Use sparingly for complex or important flows. |
| Deployment | One deployment environment | Deployment nodes, infrastructure nodes, and system/container instances | Create when environment evidence is known. |

Never create all levels mechanically. More diagrams do not imply better
documentation.

## View invariants

- Keep one abstraction level for the primary elements in each static view.
- Give every diagram a title, diagram type, scope, and key.
- Give every element a name, explicit type, and short responsibility.
- Give containers and components a verified technology when known.
- Use a single arrow direction per relationship.
- Label every relationship with intent that reads correctly in the arrow
  direction.
- Label inter-process container relationships with a protocol or mechanism when
  known.
- Explain acronyms, colours, shapes, icons, borders, and line styles.
- Keep notation, names, IDs, descriptions, and colours consistent across views.
- Make each diagram understandable without depending on a long narrative.

Prefer labels such as "Publishes order-created events to" or "Reads market
snapshots from" over "Uses". Choose dependency or data-flow semantics
deliberately and keep them consistent within a view.

## Evidence rules for reverse-engineered architecture

- Verify runtime relationships through call sites, client construction,
  configuration, framework wiring, tests, telemetry configuration, or
  infrastructure.
- Do not infer a network boundary from imports or folder boundaries.
- Do not infer a database, queue, cloud service, or protocol from naming alone.
- Distinguish a technology dependency from an architectural relationship.
- Label external ownership only when documentation, configuration, or the user
  establishes it.
- Record ambiguity rather than choosing the most plausible architecture.

## Review checklist

Before finishing, answer yes or record a limitation:

### General

- Does every diagram identify its type and scope?
- Does every diagram have a key?
- Is the intended audience clear?
- Can each view stand on its own?

### Elements

- Does every element have a stable name, explicit type, and responsibility?
- Are technologies included where applicable and supported by evidence?
- Are acronyms and visual conventions explained?
- Are boundaries and ownership unambiguous?

### Relationships

- Does every arrow have one direction and a specific label?
- Does each label agree with the arrow direction?
- Are inter-process mechanisms or protocols shown where known?
- Are static relationships consistent with dynamic views?

### Collection

- Do zoom levels transition coherently?
- Are names and IDs stable across views?
- Are current and proposed states unmistakably separated?
- Are assumptions, unknowns, and coverage limitations visible?
- Are diagrams small enough to read?
