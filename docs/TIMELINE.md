# Source-coordinate timeline

The original media is immutable. Transcript words use stable IDs and integer
source ticks. Operations refer to source intervals or word IDs; output time is
derived only after replay. A cut therefore does not change where a later edit
points, and restoring an operation recomputes the timeline from the history.

`app/core/timeline.py` is the new pure replay boundary. Its `Timeline` keeps the
source duration, word records, and ordered operations. `replay(timeline,
cursor)` folds active operations into retained segments. Speed is represented
as an integer numerator/denominator. `src_to_out` and `out_to_src` map through
the derived segment list. `canonical_hash` serializes integer and string state
as sorted compact JSON before hashing.

History state is `active`, `undone`, or `disabled`. Undo and redo update that
state and replay; restore disables one operation and replays all remaining
active operations. Appending after undo disables the undone branch. Operation
IDs are caller supplied and should be stable sequence identifiers, never UUIDs.

The existing editor continues to use its legacy float-second `Timeline` while
callers are migrated. The new core is intentionally isolated so API, UI, and
rendering behavior can be moved in later phases without replacing tested
features all at once. Frame conversion belongs at the renderer boundary; source
tick arithmetic remains integer throughout the editing core.
