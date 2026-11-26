"""ENG-03 authorization decision service.

Implements docs/sd/authorization-and-approval.md on top of the ENG-01
specs/domain/*.schema.json contracts: DecisionRequest lifecycle, canonical
payload hashing, ApprovalRecord/ApprovalRevocation issuance, ExecutionAuthorization
issuance from a policy grant or an approval, AuthorizationUse consumption and
the pre-dispatch recheck.

Persistence here (repository.InMemoryAuthorizationRepository) is an explicit
stand-in for the ENG-02 database layer: every repository call is written
against the AuthorizationRepository protocol so ENG-02's Postgres-backed
implementation can be substituted without changing AuthorizationService.
"""
