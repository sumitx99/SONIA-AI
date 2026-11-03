"use client";

import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { ChevronRight, Ellipsis, HelpCircle, Loader2, LogOut, Plug, Settings, SlidersHorizontal, Upload, UserRound } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { ConnectionsPanel } from "@/components/connections-panel";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { deleteAvatar, loadProfile, updateProfile, uploadAvatar, type AccountProfile, type ProfileDetails } from "@/lib/api";

const empty: AccountProfile = { display_name: "", bio: "", reduce_motion: false, compact_mode: false, avatar_url: null, avatar_expires_at: null };
type Section = "profile" | "personalization" | "settings" | "connections" | "help";
const sections = [
  { id: "profile" as const, title: "Profile", icon: UserRound },
  { id: "personalization" as const, title: "Personalization", icon: SlidersHorizontal },
  { id: "settings" as const, title: "Settings", icon: Settings },
  { id: "connections" as const, title: "Connections", icon: Plug },
  { id: "help" as const, title: "Help", icon: HelpCircle },
];

export function AccountMenu({ userId, email, initialName, onSignOut, onPreferences }: {
  userId: string; email: string; initialName?: string; onSignOut: () => Promise<void>;
  onPreferences: (preferences: Pick<AccountProfile, "reduce_motion" | "compact_mode">) => void;
}) {
  const [profile, setProfile] = useState<AccountProfile>(empty);
  const [draft, setDraft] = useState<ProfileDetails>(empty);
  const [section, setSection] = useState<Section | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [imageFailed, setImageFailed] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const preferenceCallback = useRef(onPreferences);
  preferenceCallback.current = onPreferences;
  const displayName = profile.display_name || initialName || email.split("@")[0] || "Your account";
  const initials = displayName.split(/\s+/).slice(0, 2).map(word => word[0]).join("").toUpperCase();

  useEffect(() => {
    let disposed = false;
    setLoading(true);
    loadProfile(userId).then(value => {
      if (disposed) return;
      setProfile(value); setDraft(value); preferenceCallback.current(value); setError("");
    }).catch(reason => { if (!disposed) setError(reason instanceof Error ? reason.message : "Your profile could not be loaded."); })
      .finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, [userId]);

  useEffect(() => { setImageFailed(false); }, [profile.avatar_url]);
  useEffect(() => {
    if (!profile.avatar_expires_at) return;
    let disposed = false;
    const timer = window.setTimeout(() => {
      loadProfile(userId).then(value => { if (!disposed) setProfile(value); }).catch(() => { if (!disposed) setImageFailed(true); });
    }, Math.max(5000, (profile.avatar_expires_at * 1000 - Date.now()) * .8));
    return () => { disposed = true; window.clearTimeout(timer); };
  }, [profile.avatar_expires_at, userId]);

  function open(next: Section) { setDraft(profile); setNotice(""); setSection(next); }
  function apply(value: AccountProfile) { setProfile(value); preferenceCallback.current(value); }
  async function save() {
    setBusy(true); setError(""); setNotice("");
    try { const value = await updateProfile(draft, userId); apply(value); setDraft(value); setNotice("Changes saved to your account."); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Changes could not be saved."); }
    finally { setBusy(false); }
  }
  async function changePhoto(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; event.target.value = "";
    if (!file) return;
    setNotice(""); setError("");
    if (file.size > 5 * 1024 * 1024) { setError("Choose an image smaller than 5 MB."); return; }
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) { setError("Choose a PNG, JPEG, or WebP image."); return; }
    setBusy(true);
    try { const value = await uploadAvatar(file, userId); apply(value); setNotice("Profile photo saved."); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Your photo could not be saved."); }
    finally { setBusy(false); }
  }
  async function removePhoto() {
    setBusy(true); setError(""); setNotice("");
    try { apply(await deleteAvatar(userId)); setNotice("Profile photo removed."); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Your photo could not be removed."); }
    finally { setBusy(false); }
  }
  const avatar = (large = false) => <span className={`account-avatar ${large ? "account-avatar-large" : ""}`}>
    {profile.avatar_url && !imageFailed ? <img src={profile.avatar_url} alt={`${displayName}'s profile photo`} onError={() => setImageFailed(true)} /> : initials}
  </span>;

  return <>
    <DropdownMenu>
      <DropdownMenuTrigger asChild><button className="account-menu-trigger" type="button" aria-label="Open account menu">
        {avatar()}<span><strong>{displayName}</strong><small>Your account</small></span><Ellipsis size={17} />
      </button></DropdownMenuTrigger>
      <DropdownMenuContent data-reduce-motion={profile.reduce_motion} className="account-popover" side="top" align="start" sideOffset={8}>
        <DropdownMenuItem className="account-popover-user" onSelect={() => open("profile")}>
          {avatar()}<span><strong>{displayName}</strong><small>{email}</small></span><ChevronRight size={16} />
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {sections.slice(0, 4).map(item => <DropdownMenuItem key={item.id} onSelect={() => open(item.id)}><item.icon size={18} />{item.title}</DropdownMenuItem>)}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => open("help")}><HelpCircle size={18} />Help<ChevronRight size={15} className="account-menu-chevron" /></DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="account-logout" onSelect={() => { void onSignOut(); }}><LogOut size={18} />Log out</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    <Dialog open={section !== null} onOpenChange={value => { if (!value && !busy) setSection(null); }}>
      <DialogContent className="account-settings-dialog">
        <DialogTitle>{sections.find(item => item.id === section)?.title || "Your account"}</DialogTitle>
        <DialogDescription className="account-settings-description">Your Sonia account, made a little more yours.</DialogDescription>
        <div className="account-settings-layout">
          <nav aria-label="Account settings">{sections.map(item => <button disabled={busy} type="button" key={item.id} aria-current={section === item.id ? "page" : undefined} onClick={() => open(item.id)}><item.icon size={16} />{item.title}</button>)}</nav>
          <div className="account-settings-content" aria-busy={busy || loading}>
            {loading ? <p className="account-settings-loading"><Loader2 size={16} className="animate-spin" />Loading your profile…</p> : <>
              {section === "profile" && <><div className="account-photo-editor">{avatar(true)}<div><button type="button" disabled={busy || profile === empty} className="account-secondary-button" onClick={() => fileInput.current?.click()}><Upload size={14} />{busy ? "Updating…" : "Change photo"}</button>{profile.avatar_url && <button type="button" className="account-remove-photo" disabled={busy} onClick={removePhoto}>Remove photo</button>}<p>PNG, JPEG or WebP · Up to 5 MB<br />Photos are cropped to a square.</p></div></div>
                <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" aria-label="Choose a profile photo" onChange={changePhoto} disabled={busy} />
                <label className="account-settings-field">Display name<input value={draft.display_name} placeholder={initialName || "Your name"} maxLength={100} disabled={busy} onChange={event => setDraft({...draft, display_name:event.target.value})} /></label>
                <label className="account-settings-field">Email<input value={email} readOnly /></label>
                <label className="account-settings-field">About you <span className="account-optional">Optional</span><textarea value={draft.bio} placeholder="A little about you" maxLength={500} disabled={busy} onChange={event => setDraft({...draft, bio:event.target.value})} /><small>Private profile information. {draft.bio.length}/500</small></label>
              </>}
              {section === "personalization" && <><h3>Make space for your way of working.</h3><p className="account-section-copy">These display preferences follow your account.</p><label className="account-preference"><span><strong>Compact conversations</strong><small>Show more conversations in the sidebar.</small></span><input type="checkbox" checked={draft.compact_mode} disabled={busy} onChange={event => setDraft({...draft, compact_mode:event.target.checked})} /></label><label className="account-preference"><span><strong>Reduce motion</strong><small>Use a calmer workspace with fewer animations.</small></span><input type="checkbox" checked={draft.reduce_motion} disabled={busy} onChange={event => setDraft({...draft, reduce_motion:event.target.checked})} /></label></>}
              {section === "settings" && <><h3>Account &amp; history</h3><div className="account-info-block"><span>Signed in as</span><strong>{email}</strong></div><div className="account-info-block"><span>Chat history</span><p>New conversations, questions and answers are saved to this account. Use the conversation menu to rename or delete a chat.</p></div><button type="button" className="account-secondary-button" onClick={() => { void onSignOut(); }}><LogOut size={15} />Log out of Sonia</button></>}
              {section === "connections" && <ConnectionsPanel />}
              {section === "help" && <div className="account-help"><h3>A few things to know.</h3><details open><summary>How do I start?</summary><p>Choose New conversation, add a PDF, and ask a question about it. PDFs can be up to 25 MB.</p></details><details><summary>Where is my history?</summary><p>Your saved conversations appear in the sidebar when you sign in to the same account. Older document-only chats may not contain messages from the previous version.</p></details><details><summary>How do profile photos work?</summary><p>Your uploaded photo is saved privately. You can replace or remove it in Profile at any time.</p></details></div>}
            </>}
            {error && <div role="alert" className="account-settings-error">{error}{!loading && profile === empty && <button type="button" disabled={busy} onClick={() => { setLoading(true); loadProfile(userId).then(value => { apply(value); setDraft(value); setError(""); }).catch(reason => setError(reason instanceof Error ? reason.message : "Please try again.")).finally(() => setLoading(false)); }}>Retry loading profile</button>}</div>}
            {notice && <p role="status" className="account-settings-notice">{notice}</p>}
            {(section === "profile" || section === "personalization") && <div className="account-settings-actions"><button type="button" className="account-save-button" disabled={loading || busy || !!error && profile === empty} onClick={save}>{busy && <Loader2 size={14} className="animate-spin" />}Save changes</button></div>}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  </>;
}
