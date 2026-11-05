# Compatibility

Updated November 5, 2026; local RC4 artifact evidence dates to October 7. **Historical observations and source behavior are not
release-candidate certification.** Local **0.3.0 RC4, build 6** has an inspected macOS 15.0 floor; gameplay
qualification remains pending. See [release readiness](RELEASE.md).

| Area | Evidence | Current-candidate status |
| --- | --- | --- |
| Apple Silicon | Required by launcher source | Target platform; clean-machine verification pending |
| M4 Pro, 24 GB, macOS 15.3.1 | Earlier standalone gameplay recorded September 30 | Historical only; not the new app bundle |
| MacBook Air M1, 16 GB | Maintainer reports it working; exact OS/revision/scenarios unrecorded | Reported working; clean-machine and exact-candidate qualification pending |
| Minimum macOS | 0.3.0 RC4 whole-bundle audit: 15.0 across 95 native files | Clean-M1 / game execution on the minimum OS untested |
| Intel Mac | Rejected by launcher hardware check | Unsupported |
| Rosetta | Required for x86-64 Wine/graphics/game path | Required; native ARM game execution is not shipped |
| Minecraft edition | Helper checks Microsoft entitlement for Minecraft for Windows | A console/mobile purchase alone is not proof of this entitlement |
| Game version | Fresh replacement-helper output config: 1.26.5203.0; earlier gameplay notes use 1.26.52 | Catalog can change; RC3 in-game version is not yet recorded in the bounded session result |
| First owned-game download | Same-Mac RC2 reached sign-in/catalog; four initial HTTPS GETs returned 404 | Old route failed in RC2 and was retained in RC3; exact replacement helper passed outside app and is now in RC4. RC4 native first-run pending |
| Packaged graphics probes | Actual RC3 GPU presentation/readback/texture/discard passed; resources/signature intact | Probe pass only; game/font behavior and save acceptance pending |
| RC3 functioning / exit | User-confirmed same-Mac functioning with copied owned payload; normal return supported by UI/process cleanup | Bounded pass; save/reopen, soak and clean-M1 remain unverified |
| Local worlds | Earlier development save/reopen observed | Current candidate save/reopen and clean-M1 test pending |
| Xbox / PlayStation friend worlds | Maintainer estimates 10+ cumulative hours across repeated friend sessions (October 20 report); two monitored sessions in [gameplay evidence](history/GAMEPLAY.md#repeated-cross-platform-play) | New packaged-candidate join/disconnect/rejoin still needs recording |
| Minecraft Social parties | October 25 Create party failure traced to duplicate PlayFab HTTP writes; temporary callback-order correction succeeded in game; compiled source fix passed isolated native tests ([evidence](history/PARTY-WINHTTP-2026-10-25.md)) | October 31: installed compiled fix passed all three native write tests; host reported the friend-world retry worked on 26.60. Party creation/invites and broader joining acceptance remain unverified |
| Featured servers | Earlier lobby entry observed | Candidate untested |
| Realms | Earlier joined-Realm list observed | Active Realm entry untested |
| Marketplace / controllers | No complete qualification record | Untested; no blanket support claim |
| Custom skin import | October 19 local native checks passed dialog/cancellation and PNG import/rendering, including a Unicode filename | Picker crash no longer reproduces locally; #4 awaits reporter verification. 26.52 restart reset matches an [upstream bug](history/TESTING.md#october-20-skin-persistence-diagnosis); newer-game validation and world import/export regression pending |
| Offline launch | Account verified on Play | Unsupported |
| Store market | Native Settings saves a two-letter country code (default CA); Play and updates pass it to the helper | Offline propagation fixtures exist; real-account behavior in other markets remains unverified |
| Cancel while waiting for Keychain | Actual RC3 native Cancel stopped helper; no socket/prefix/game; imported payload key hashes unchanged | Passed only this stage; retry/authentication/gameplay remain untested |
| App/game updates | Manual app replacement; **Update Minecraft…** downloads a new game and retains backups | Candidate live upgrade and recovery test pending |
| Signing / Gatekeeper | Local ad-hoc builds; no public notarized app | Developer ID/notarization is an external blocker |

Record the actual Mac, macOS, app hash, game version, and scenario when reporting
a result. A menu, server list, or screenshot cannot prove a completed multiplayer
session. See [historical session details](STABILITY.md) and
[backup/update instructions](USER_GUIDE.md#your-files-backups-and-updates).
