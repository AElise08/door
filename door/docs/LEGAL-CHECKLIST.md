# Legal checklist (not legal advice — have a lawyer review before selling)

- [ ] Terms of service: questions-only product, no warranty on answers, customer is responsible for what they export and whom they authorize.
- [ ] Privacy policy: what is stored (guest phone numbers, questions, answers for 30 days, usage metadata), where, and who can see it.
- [ ] Data-protection roles: the customer is the controller for their guests' data; you are the processor. Data-processing agreement ready.
- [ ] Guest notice: guests should be told by the customer that questions are logged and visible to the owner (e.g. in the first reply or onboarding text).
- [ ] Model provider terms: the customer's API key and the provider's usage policy apply; files the agent reads are sent to that provider.
- [ ] SMS provider terms (Plow or replacement): permitted use, resale, opt-out/STOP handling, regional rules for business texting.
- [ ] Retention: 30-day purge exists in code; decide whether to offer shorter/longer and document it.
- [ ] Incident process: who is told, how fast, if tokens or data leak. `rotate` and `disable` exist for tokens.
