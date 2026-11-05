# Using Bedrock for Mac

**Local RC4 is a test candidate.** Native first-run, update, gameplay and clean-M1
qualification remain open in the [release record](RELEASE.md).

This is an open-source preview. There is no public notarized installer yet.
The steps below describe a complete local app built from this repository;
GitHub's **Download ZIP** contains source, not an installable app. Developers can
follow [the build guide](DEVELOPMENT.md). To play directly from source using
`Start.command`, begin with [the README](../README.md#start-from-source). Source
setup installs build tools and compiles locally; the app instructions below
apply to a complete bundle.

## Before you start

- An Apple Silicon Mac. Intel Macs are not supported by the current launcher.
- macOS **15.0 or later** for local 0.3.0 RC4 (build 6), based on the complete
  binary audit. Gameplay qualification remains pending; see
  [compatibility](COMPATIBILITY.md). Check the manifest again for later builds.
- Rosetta, which runs the Intel-based Wine and graphics components. Follow
  [Apple's Rosetta instructions](https://support.apple.com/en-us/102527).
- An internet connection and a Microsoft account that owns **Minecraft for
  Windows**. Ownership only on a console or phone does not establish that PC
  entitlement. The launcher checks the account's actual license with Microsoft.
- At least 8 GB free for game setup; leave more room for worlds, backups, and
  temporary files. This is not the storage budget for compiling the project.

The current launcher verifies the account on each Play action. It has no
supported offline-launch mode. Choose **Bedrock for Mac → Settings…** to set
your Microsoft Store country using a two-letter code, such as `CA`, `US`, `GB`
or `TR`, then choose **Save**. The default is `CA`. The saved country applies
to your next Play or game update; wait for setup or Minecraft to finish before
changing it. The CLI also accepts `--market`.

## Install, sign in, and play

1. Open your locally built `.dmg` and drag **Bedrock for Mac** onto its
   **Applications** shortcut. Eject the disk image after copying finishes.
2. Open **Bedrock for Mac** from Applications and click **Install & Play**.
3. Complete Microsoft sign-in with the account that owns the Windows game.
4. Let setup download Minecraft and the required Microsoft component. There
   are no separate Homebrew, Python, compiler, Wine, or DXMT installs for players
   using the complete app bundle.
5. If Minecraft shows its welcome screen, select **Sign in now** to use the
   Microsoft session. Confirm your expected gamertag in the game.

Later launches show **Play**. After an app/runtime change, **Finish setup** with
**Continue** means the existing game needs preparation; it is not a request to
buy or download the game again. Quit Minecraft normally to finish the session.
You can close the launcher window while playing; the launcher keeps its account
service running until Minecraft exits. Reopen the app to return to its window.

**Cancel** stops the current setup attempt and keeps completed installation steps and worlds.
Choose **Continue** to retry. An interrupted game-file download restarts; it is
not a resumable transfer. Avoid starting multiple copies of the app.

## Understand the Mac prompts

Permission to open a downloaded app and permission to read saved credentials
are separate. Current builds are ad-hoc signed and not notarized, so they may
not show the same first-open experience as an identified developer's app.
Use [Apple's app-opening guidance](https://support.apple.com/en-us/102445) for a
build whose source you trust. Do not disable Gatekeeper globally.

The account helper may appear as `standalone_helper` and request the
**Minecraft Bedrock Standalone** Keychain item. **Allow** (or **Allow Once**)
authorizes one request; **Always Allow** remembers access for that helper.
Only choose it when you recognize and trust the app. See
[Apple's Keychain explanation](https://support.apple.com/guide/keychain-access/kyca1243/mac).
The password requested by macOS unlocks your Keychain; it is not your Microsoft
password. Never share it in a bug report or with an automated agent.

On October 2, a repeat launch of the unchanged, authorized development build
was confirmed prompt-free.
Changing the helper's ad-hoc signature can request authorization again. A
promise of zero prompts after every update would be inaccurate.

## Accounts and game features

Use **Bedrock for Mac → Sign Out of Microsoft…** while the game is closed to
change accounts. Sign-out keeps the game and worlds. The next Play action asks
for Microsoft sign-in and checks the new account's ownership.

This is a compatibility project, not an official Microsoft Mac edition.
Local gameplay, a featured-server lobby, and listing joined Realms have been
observed. Xbox and PS5 friend-world play were also confirmed on the earlier
standalone stability build; see [the dated evidence](STABILITY.md). Active Realm
entry, combined native-build multiplayer, and every Marketplace feature remain
unverified. Keep Xbox permissions and game versions in mind
when reporting multiplayer issues; do not assume a visible server or Realm list
proves a successful online session. See [the current evidence](RELEASE.md).

## Your files, backups, and updates

Choose **Help → Open Game Data**. Alternatively, in Finder choose
**Go → Go to Folder…** and enter:

```text
~/Library/Application Support/Bedrock for Mac/
```

| Folder | Contents |
| --- | --- |
| `game` | Downloaded Minecraft program and package metadata |
| `bottles/Bedrock-Standalone` | Windows environment, game settings, and local worlds |
| `logs/standalone` | Setup, account, prefix, and game diagnostics |
| `runtime`, `sources` | Runtime links, helper link, and session records |
| `downloads` | Locally acquired component downloads, if present |
| `game-backups` | Previous game/prefix copies retained by completed manual game updates |

For `Start.command` and the source CLI, the data root is the **checkout folder**,
and worlds live in `<checkout>/bottles/Bedrock-Standalone`. Keep that folder when
updating source. The source setup does not automatically migrate data into the
packaged app. The app menu actions below apply to the native launcher.

Worlds are inside the prefix's `drive_c/users/<wine-user>/AppData/Roaming/Minecraft Bedrock/`
tree, under the account's `games/com.mojang/minecraftWorlds` directory. The Wine
user and account folder names vary. Do not assume a world is stored in `game/`.

For a backup, quit Minecraft normally, wait for **Play**, and quit the launcher.
Copy the entire `bottles/Bedrock-Standalone` folder to a dated location outside
the app's data directory. Keep backups private: they can contain account and
game settings. A full data-directory backup is useful for troubleshooting but
does not replace the app bundle or export your macOS Keychain credentials.

To restore on the same Mac and data location, close the game and launcher,
preserve the current prefix under a
different name, and copy the backup back to `bottles/Bedrock-Standalone`. Keep
both copies until you have opened the expected world successfully. Restore and
world save/reopen are still items in the clean-Mac validation plan; never test
them on your only copy of a world.
Moving a prefix to a different Mac/user can leave absolute Wine drive mappings
pointing at the old location; cross-Mac migration is not a supported automatic
workflow.

There is no automatic app or game updater. For an app update, back up the prefix,
close the game and launcher, and replace only the application in Applications.
The next launch reconnects to the existing data. Keep the previous app until
the update works; a game or prefix changed by a newer version may need its
matching backup when rolling back. Existing game files are reused, so replacing
the app does not itself download a new Minecraft version.

To update Minecraft itself, quit the game and choose **Bedrock for Mac →
Update Minecraft…**, then confirm. The current source downloads the latest
version available to your Microsoft account into a separate folder, keeps a
copy of your prefix plus the previous game, and prepares the new version. It
returns to **Play** when finished. This needs at least 8 GB free **plus** room
for a copy of your worlds/settings. It is a manual action, not an automatic update.

Successful updates keep `previous-game` and `previous-prefix` under a unique
`game-backups/minecraft-…` folder. Keep these private and retain them until you
have verified your worlds. They supplement your independent backup. The recovery
path restores the prior installation if activation/preparation fails or is
cancelled. Recovery also retains displaced newer files in `game-backups`;
check both versions before deciding which world to keep. After an interrupted
update, choose **Continue** to recover before trying again. If recovery reports conflicting files, preserve everything and
report the error; do not delete the transaction or prefix. Live game-update and
recovery validation remain release gates. If an interrupted Wine setup still
owns the prefix, wait for it to exit or restart the Mac normally; the app refuses
to kill an ambiguous process to force recovery.

If multiplayer reports a version mismatch, compare Minecraft versions on both
devices and use this game-update action when appropriate. Replacing only the
launcher does not update an existing game. A newer game can change world data;
do not downgrade your only copy of a world or assume an old game can read it.

To uninstall the app while retaining saves, close both programs and move the
application to Trash. Its data directory and Keychain item remain. To reclaim
game storage, first back up worlds, then deliberately remove only the data you
intend to discard. Sign out through the app before removing it if you also want
to clear its saved user session. No automatic CrossOver world migration exists.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| Rosetta or macOS requirement error | Check the prerequisites above. Moving the app cannot change its minimum OS. |
| Microsoft window closed or sign-in timed out | Choose **Try Again** and complete sign-in. Returning-account waits are bounded to 15 minutes; initial download sessions to two hours. |
| Keychain access denied | Retry and handle the macOS prompt yourself. Do not delete credentials as a first troubleshooting step. |
| Keychain prompt on every launch | Check whether you chose **Allow** instead of **Always Allow**, or rebuilt/replaced the helper. Report prompts from an unchanged build separately. |
| Purchase or content-license error | Verify the signed-in account owns Minecraft for Windows. Sign out and switch accounts if needed. |
| Game/component connection error | Check connectivity, then retry. Report the exact stage if it persists; a successful Microsoft login does not prove the download service is reachable. |
| Incomplete existing game | Close Minecraft and choose **Update Minecraft…** to repair using a fresh owned-game download. Keep worlds and backups; never remove `bottles` to repair a download. |
| Another setup/helper is running | Return to the active launcher, finish or cancel setup, or quit Minecraft normally. Do not delete `/tmp/xodus.sock` or kill every Wine process. If the conflict persists after a normal restart, report it. |
| Minecraft exits or shows a blank window | Keep your saves. Record the game version and whether the failure followed a runtime/app update; include a short reviewed error excerpt. |
| Imported skin resets after restarting 26.52 | Keep the original skin PNG and reimport it when needed. This matches Mojang's [MCPE-241720](https://bugs.mojang.com/browse/MCPE-241720); a fix is announced in 26.60.24 Preview, which has not been validated here. |

Use **Help → Open Setup Logs** (or **Open Setup Log** on an error screen).
`onboarding.log` covers the overall setup; `account.log` covers the helper;
`prefix-setup.log` covers Wine preparation; `minecraft-*.log` covers game sessions.
Logs are local and are not automatically submitted as bug reports.

Report a reproducible problem with the
[GitHub bug template](https://github.com/1JRobertson/bedrock-mac/issues/new?template=bug_report.yml).
Include macOS version, chip, app/source revision, game version, last visible
stage, and whether this was a first install, retry, or update. Review excerpts
before posting: omit passwords, tokens, email addresses, signed URLs, and full
unreviewed logs. Use [SECURITY.md](../SECURITY.md) for security reports.
