## ADDED Requirements

### Requirement: Config declares project identity and phase
The config SHALL declare project name, description, current phase, and last updated date to establish context for AI artifact generation.

#### Scenario: AI assistant reads project context
- **WHEN** an AI assistant creates an OpenSpec artifact
- **THEN** it knows the project is a DFT acceleration research prototype for Quantum ESPRESSO subspace diagonalization with CIM-oriented backend

### Requirement: Config declares tech stack with versions
The config SHALL list all programming languages, frameworks, build systems, and key dependencies with minimum versions.

#### Scenario: AI assistant generates code examples
- **WHEN** an AI assistant writes C++ code in a spec or design doc
- **THEN** it uses C++17 features, not C++20 or C++14

#### Scenario: AI assistant references Python dependencies
- **WHEN** an AI assistant writes Python test code
- **THEN** it assumes Python 3.9+, pytest, and standard library only (no external ML frameworks unless explicitly requested)

### Requirement: Config declares domain knowledge
The config SHALL summarize the scientific domain, key algorithms, and system architecture to enable domain-aware artifact generation.

#### Scenario: AI assistant explains a design decision
- **WHEN** an AI assistant discusses memory hierarchy trade-offs
- **THEN** it understands CIM (Compute-In-Memory) constraints and near-SRAM residency requirements

### Requirement: Config declares naming and style conventions
The config SHALL specify naming conventions, indentation, brace style, and code organization rules.

#### Scenario: AI assistant creates a new Python module
- **WHEN** an AI assistant writes a new DSE v2 module
- **THEN** it uses snake_case for functions, UpperCamelCase for types, and 4-space indentation

### Requirement: Config declares per-artifact rules
The config SHALL define formatting and content rules for proposals, designs, specs, and tasks.

#### Scenario: AI assistant creates a proposal
- **WHEN** an AI assistant writes a proposal.md
- **THEN** it includes a "Non-goals" section and keeps proposals under 2 pages

#### Scenario: AI assistant creates tasks
- **WHEN** an AI assistant writes a tasks.md
- **THEN** it breaks tasks into chunks of max 4 hours and includes verification steps

### Requirement: Config declares testing and validation conventions
The config SHALL specify test frameworks, coverage expectations, and validation gates.

#### Scenario: AI assistant implements a feature
- **WHEN** an AI assistant writes implementation code
- **THEN** it includes corresponding tests and expects all 79 DSE v2 tests to pass

### Requirement: Config declares documentation conventions
The config SHALL specify where design rationale, API docs, and validation notes belong.

#### Scenario: AI assistant documents a design decision
- **WHEN** an AI assistant explains why a mapping algorithm was chosen
- **THEN** it places rationale in `docs/` or `dse_v2/docs/`, not buried in source comments
