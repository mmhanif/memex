# Memex

A personal, offline workspace for one manager to track their portfolio of work, their people, and the commitments between them, stored as plain Markdown files.

## Workspace

**Workspace**:
The user's folder of Markdown files that holds all Memex data, kept separate from the application.
_Avoid_: Vault, repo, database

**Note**:
Any Markdown file in the Workspace; the base everything else is a typed kind of.
_Avoid_: Page, document

**Entity**:
A Note with a declared type (Theme, Project, Deliverable, Person, To-do, Glossary Term) that others can reference.
_Avoid_: Record, object, item

## Portfolio

**Theme**:
A long-lived area of focus that groups Projects; has no status of its own.
_Avoid_: Programme, initiative, area

**Project**:
A piece of work under at most one Theme, with a status and optional due date.
_Avoid_: Workstream, initiative

**Deliverable**:
A concrete output under one Project, with a status and optional due date.
_Avoid_: Milestone, task, output

## People

**Person**:
Anyone the user tracks: a Team Member, a Stakeholder, or both.
_Avoid_: Contact, user, member

**Team Member**:
A Person in the user's reporting hierarchy.
_Avoid_: Report, employee, staff

**Stakeholder**:
A Person with an interest in a Theme, Project or Deliverable, usually outside the user's team.
_Avoid_: Sponsor, customer, client

**Me**:
The single Person who is the user of this Workspace.
_Avoid_: Owner, self, current user

**Manager**:
The Person a Team Member reports to.
_Avoid_: Boss, lead, supervisor

**Direct**:
A Person whose Manager is Me.
_Avoid_: Direct report, DR, subordinate

**Tag**:
A link from a Person to a Theme, Project or Deliverable, meaning they are involved in it.
_Avoid_: Assignment, mention, label

## Commitments

**To-do**:
A commitment with an Owner who must do it and a Requester who is waiting on it; either may be Me.
_Avoid_: Task, action item, action

**Owner**:
The Person who must complete a To-do.
_Avoid_: Assignee, doer

**Requester**:
The Person waiting on a To-do to be completed.
_Avoid_: Requestor, creator, waiter

## Reference

**Glossary Term**:
A term or phrase from the user's work, with its definition.
_Avoid_: Definition, acronym, jargon

**Bookmark**:
A saved external link with an optional title and tags.
_Avoid_: Link, favourite, URL

## Views

**Person View**:
The page for one Person showing their Tags, the To-dos Me is waiting on from them, and the To-dos they are waiting on from Me.
_Avoid_: Profile, 1:1 page

**Mind Map**:
A read-only radial diagram centred on a Theme, on Me's Directs, or on Stakeholders.
_Avoid_: Graph, network view, org chart
