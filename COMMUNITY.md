# Community

Two boards use the existing Supabase posts/comments schema and owner RLS:
`free` and `build_share`. Public GET endpoints expose posts and comments;
authenticated mutations validate ownership server-side in addition to RLS.
No service-role credentials are used. Notice creation is not exposed.

Routes under /api/community:
- GET/POST /posts (board, offset, title search on GET)
- GET /posts/{id}
- POST /posts/{id}/edit and /delete
- GET/POST /posts/{id}/comments
- POST /comments/{id}/edit and /delete

The Next BFF retains HttpOnly auth cookies, checks same-origin mutations and
refreshes expired sessions. Rendering uses plain React text, not raw HTML.
Deletion is permanent and the UI asks for confirmation; deleting a post also
deletes its comments according to the existing database cascade.

A shared build must belong to the author. The post stores a versioned public
snapshot inside content with a format marker, body, and allowlisted parts/prices.
It retains the build_id relationship but does not make the source build public.
Private prompts, owned-part notes and raw specification metadata are omitted.
Editing a post preserves its attached snapshot. A saved build requires the
current version-1 AI snapshot format. The attachment selector shows the latest
ten saved estimates. Images/uploads and nested replies are not implemented.

The home dashboard shows the latest three posts per board, not a fabricated
popularity ranking. New installations need no additional schema migration if
they have the existing COMBEE tables/policies from the supplied backup.

Validation: unit tests cover public reads, auth, owner-only mutations,
attachment ownership and omission of private fields. Live reads verify the
Supabase join/schema; no synthetic public posts are created during UI QA.
