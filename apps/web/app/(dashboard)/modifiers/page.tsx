import { redirect } from "next/navigation";

/**
 * Modifiers moved under the menu page as a tab — see
 * `app/(dashboard)/menu/menu-client.tsx`. This route is kept so old
 * links and bookmarks land on the add-ons tab instead of a 404.
 */
export default function ModifiersPage() {
  redirect("/menu?tab=addons");
}
