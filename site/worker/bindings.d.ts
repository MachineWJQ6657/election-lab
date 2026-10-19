// D1 is optional in this Site's hosting manifest. Keep the scaffold's runtime
// guard typed without declaring a database that is provisioned nowhere.
declare namespace Cloudflare {
  interface Env {
    DB?: D1Database;
  }
}
