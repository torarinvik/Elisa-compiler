/*
 * The Stage0 test fixture creates only an empty stack darray, but its generated
 * main still calls arena_free for the implicit empty owner. No storage was
 * allocated, so a no-op is the complete runtime behavior needed by this test.
 */
void arena_free(void *arena) { (void)arena; }
