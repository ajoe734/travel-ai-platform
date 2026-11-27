# 0006 Voice and multimedia handoff

ENG-10 adds tenant-scoped durable records for WebRTC and **SIP_TEST** sessions,
voice turns, playback interruption, real transfer outcomes, asynchronous media
intake, and a payment-link handoff.  It never stores PAN/CVV and does not add
a production telecom credential or claim that a SIP provider is connected.

The down migration is only for an empty/disposable database.  In an environment
with session, recording-policy, transfer, or payment-handoff evidence, retain
the rows and use a forward migration.
