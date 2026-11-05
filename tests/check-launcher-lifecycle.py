#!/usr/bin/env python3
"""Run macOS launcher lifecycle regressions with a synthetic worker and no visible UI.

Requires Apple Silicon, macOS 15+, and Xcode Command Line Tools. This checks the
production controller/delegate with intercepted sheet presentation; actual SwiftUI
red-close/reopen and sheet behavior still require the native acceptance test.
"""
from pathlib import Path
import subprocess,json,datetime,hashlib,os
import argparse, tempfile, sys
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,help='New directory for fixture source, binary, logs and result; defaults to temporary output')
args=parser.parse_args()
if sys.platform != 'darwin': parser.error('This fixture requires macOS and Swift/AppKit')
repository=Path(__file__).resolve().parents[1]
src=repository/'launcher/BedrockLauncher.swift'
workspace=None
if args.output:
    base=args.output.absolute()
    base.mkdir(parents=True,exist_ok=False)
else:
    workspace=tempfile.TemporaryDirectory(prefix='bedrock-launcher-lifecycle-')
    base=Path(workspace.name)
source_bytes=src.read_bytes()
source_sha256=hashlib.sha256(source_bytes).hexdigest()
text=source_bytes.decode().split('struct LauncherView: View')[0]
old='root = path.isEmpty ? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Bedrock for Mac") : URL(fileURLWithPath: path)\n        start(check: true)'
assert old in text
text=text.replace(old,'root = URL(fileURLWithPath: CommandLine.arguments[1])')
text=text.replace('window.makeKeyAndOrderFront(nil)','/* Fixture: no window presentation. */ ()')
text=text.replace('alert.beginSheetModal(for: window)', 'captureQuitSheet(alert, window: window)')
text+='''
@MainActor enum CapturedSheets {
    static var count = 0
    static var completions: [(NSApplication.ModalResponse) -> Void] = []
}
@MainActor func captureQuitSheet(_ alert: NSAlert, window: NSWindow, completionHandler: @escaping (NSApplication.ModalResponse) -> Void) {
    CapturedSheets.count += 1
    CapturedSheets.completions.append(completionHandler)
}
@MainActor final class FixtureWindow: NSWindow {
    var reopenCalls=0
    var hideCalls=0
    override func makeKeyAndOrderFront(_ sender: Any?) { reopenCalls += 1 }
    override func orderOut(_ sender: Any?) { hideCalls += 1; super.orderOut(sender) }
}
@MainActor final class OriginalWindowDelegate: NSObject, NSWindowDelegate {
    var closeCalls=0
    func windowShouldClose(_ sender:NSWindow)->Bool { closeCalls += 1; return false }
}
@main struct QuitFixture {
 @MainActor static func main() throws {
    _ = NSApplication.shared
    NSApp.setActivationPolicy(.prohibited)
    let window = FixtureWindow(contentRect:NSRect(x:-2000,y:-2000,width:300,height:200),styleMask:[.titled,.closable],backing:.buffered,defer:false)
    window.isReleasedWhenClosed = false
    let preferencesName = "bedrock-launcher-fixture-" + UUID().uuidString
    let preferences = UserDefaults(suiteName: preferencesName)!
    defer { preferences.removePersistentDomain(forName: preferencesName) }
    let launcher = Launcher(preferences: preferences)
    precondition(launcher.market == "CA")
    launcher.setMarket("TR")
    precondition(launcher.market == "TR")
    precondition(Launcher(preferences: preferences).market == "TR")
    for invalid in ["", "T", "TUR", "tr", "T1", "ＴＲ", "../TR"] {
        launcher.setMarket(invalid)
        precondition(launcher.market == "TR")
    }
    launcher.running = true
    launcher.setMarket("US")
    precondition(launcher.market == "TR")
    launcher.running = false
    preferences.set("invalid", forKey: "storeMarket")
    precondition(Launcher(preferences: preferences).market == "CA")
    launcher.setMarket("TR")
    let delegate = AppDelegate()
    delegate.launcher = launcher
    delegate.attachWindow(window)
    let scripts=launcher.root.appendingPathComponent("launcher")
    try FileManager.default.createDirectory(at:scripts,withIntermediateDirectories:true)
    let worker=scripts.appendingPathComponent("setup.py")
    let finished=launcher.root.appendingPathComponent("finish")
    func pump(_ condition: () -> Bool) throws {
        let deadline=Date().addingTimeInterval(10)
        while !condition() && Date()<deadline { RunLoop.main.run(until:Date().addingTimeInterval(0.01)) }
        precondition(condition(),"Fixture timeout")
    }
    try """
import json,time,pathlib,os
parent=os.getppid()
emit=lambda s: print(json.dumps(dict(state=s,title=s,detail='',progress=None)),flush=True)
emit('playing')
while not pathlib.Path('finish').exists() and os.getppid()==parent: time.sleep(.01)
emit('ready')
""".write(to:worker,atomically:true,encoding:.utf8)
    launcher.start()
    try pump { launcher.status.state == "playing" }
    var reopened=0
    delegate.reopenWindow = { reopened += 1 }
    precondition(!delegate.applicationShouldTerminateAfterLastWindowClosed(NSApp))
    NotificationCenter.default.post(name:NSWindow.willCloseNotification,object:window)
    for _ in 0..<100 {
        precondition(!delegate.applicationShouldHandleReopen(NSApp,hasVisibleWindows:false))
        precondition(delegate.applicationShouldTerminate(NSApp) == .terminateCancel)
    }
    precondition(reopened == 1 && launcher.running && delegate.quitAlert == nil)
    delegate.attachWindow(window)
    for _ in 0..<100 { precondition(delegate.applicationShouldTerminate(NSApp) == .terminateCancel) }
    precondition(CapturedSheets.count == 1 && delegate.quitAlert != nil)
    try "done".write(to:finished,atomically:true,encoding:.utf8)
    try pump { !launcher.running && delegate.quitAlert == nil }
    precondition(launcher.status.state == "ready")
    precondition(delegate.applicationShouldTerminate(NSApp) == .terminateNow)
    // Keep Open dismisses one sheet; another quit creates exactly one fresh sheet.
    launcher.running=true
    launcher.status=Status(state:"playing",title:"playing",detail:"",progress:nil)
    precondition(delegate.applicationShouldTerminate(NSApp) == .terminateCancel)
    let oldCompletion=CapturedSheets.completions.last!
    oldCompletion(.alertFirstButtonReturn)
    precondition(delegate.quitAlert == nil)
    precondition(delegate.applicationShouldTerminate(NSApp) == .terminateCancel)
    let fresh=delegate.quitAlert
    oldCompletion(.alertSecondButtonReturn)
    precondition(delegate.quitAlert === fresh && launcher.running)
    launcher.status=Status(state:"ready",title:"ready",detail:"",progress:nil)
    try pump { delegate.quitAlert == nil }
    launcher.running=false
    // Stop Setup uses the real controller's cancellation and real dummy process.
    try """
import signal,json,time,os
parent=os.getppid()
emit=lambda s: print(json.dumps(dict(state=s,title=s,detail='',progress=None)),flush=True)
def stop(*args):
    emit('cancelled')
    raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
emit('busy')
while os.getppid()==parent: time.sleep(.01)
""".write(to:worker,atomically:true,encoding:.utf8)
    launcher.start()
    try pump { launcher.status.title == "busy" }
    precondition(delegate.applicationShouldTerminate(NSApp) == .terminateCancel)
    CapturedSheets.completions.last!(.alertSecondButtonReturn)
    try pump { !launcher.running }
    precondition(launcher.status.state == "cancelled" && delegate.quitAlert == nil)
    for state in ["checking","cancelling"] {
        launcher.running=true
        launcher.status=Status(state:state,title:state,detail:"",progress:nil)
        let count=CapturedSheets.count
        for _ in 0..<20 { precondition(delegate.applicationShouldTerminate(NSApp) == .terminateCancel) }
        precondition(CapturedSheets.count == count+1)
        launcher.running=false
        try pump { delegate.quitAlert == nil }
        precondition(delegate.applicationShouldTerminate(NSApp) == .terminateNow)
    }
    // Retry must repeat a failed sign-out, then return to Play after success.
    // Exercise both worker terminal states: installed and unprepared games.
    let attempts=launcher.root.appendingPathComponent("signout-attempts")
    for terminal in ["ready", "new"] {
        try? FileManager.default.removeItem(at:attempts)
        try """
import json,pathlib,sys
attempts=pathlib.Path('signout-attempts')
previous=json.loads(attempts.read_text()) if attempts.exists() else []
operation='sign-out' if '--sign-out' in sys.argv else 'play'
attempts.write_text(json.dumps(previous+[operation]))
state='error' if operation=='sign-out' and not previous else '\\(terminal)' if operation=='sign-out' else 'ready'
print(json.dumps(dict(state=state,title=state,detail='',progress=None)),flush=True)
raise SystemExit(1 if state=='error' else 0)
""".write(to:worker,atomically:true,encoding:.utf8)
        launcher.start(signOut:true)
        try pump { !launcher.running }
        precondition(launcher.status.state == "error")
        launcher.retry()
        try pump { !launcher.running }
        precondition(launcher.status.state == terminal)
        launcher.retry()
        try pump { !launcher.running }
        precondition(launcher.status.state == "ready")
        let operations=try JSONDecoder().decode([String].self,from:Data(contentsOf:attempts))
        precondition(operations == ["sign-out", "sign-out", "play"])
    }
    // Read the real controller's arguments in a dummy worker; never contact Microsoft.
    let marketArguments = launcher.root.appendingPathComponent("market-arguments")
    try """
import json,pathlib,sys
pathlib.Path('market-arguments').write_text(json.dumps(sys.argv[1:]))
print(json.dumps(dict(state='ready',title='ready',detail='',progress=None)),flush=True)
""".write(to:worker,atomically:true,encoding:.utf8)
    launcher.start(updateGame:true)
    try pump { !launcher.running }
    let arguments = try JSONDecoder().decode([String].self,from:Data(contentsOf:marketArguments))
    precondition(arguments == ["--market", "TR", "--update-game"])
    print("PASS: market persistence, validation, active-session guard and worker arguments; last-close keeps application; 100 no-window reopen/quit requests create one scene request; 100 repeated quits; real worker playing-to-exit; automatic dismissal; Keep Open and new prompt; stale completion isolation; real setup cancellation; checking/cancelling quit guards; failed sign-out retries sign-out and successful ready/new returns to Play")
 }
}
'''
fixture=base/'QuitFixture.swift';fixture.write_text(text)
xcrun=['/usr/bin/xcrun','--sdk','macosx','--toolchain','default']
# Swift dispatches by argv[0]; resolving swiftc's symlink invokes swift-frontend.
compiler=Path(subprocess.check_output([*xcrun,'--find','swiftc'],text=True).strip()).absolute()
sdk=subprocess.check_output([*xcrun,'--show-sdk-path'],text=True).strip()
compiler_env={**os.environ,'SDKROOT':sdk}
include=compiler.parents[1]/'include/swift'
legacy,bridging=include/'module.modulemap',include/'bridging.modulemap'
flags=[]
if legacy.is_file() and bridging.is_file() and all('module SwiftBridging' in f.read_text() for f in (legacy,bridging)):
    empty=base/'empty.modulemap';empty.write_text('')
    overlay=base/'swift-overlay.json';overlay.write_text(json.dumps({'version':0,'roots':[{'type':'file','name':str(legacy),'external-contents':str(empty)}]}))
    flags=['-vfsoverlay',str(overlay),'-Xcc','-ivfsoverlay','-Xcc',str(overlay)]
cmd=[str(compiler),*flags,'-sdk',sdk,'-parse-as-library','-Onone','-g','-target','arm64-apple-macos15.0','-module-cache-path',str(base/'module-cache'),str(fixture),'-o',str(base/'quit-fixture')]
with (base/'build.log').open('w') as log:
    result=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,env=compiler_env)
if result.returncode:
    sys.stderr.write((base/'build.log').read_text())
    raise SystemExit(result.returncode)

import tempfile
with tempfile.TemporaryDirectory(prefix='bedrock-quit-fixture-') as data:
 p=subprocess.run([str(base/'quit-fixture'),data],capture_output=True,text=True,timeout=30)
 (base/'test.log').write_text(p.stdout+p.stderr)
 if p.returncode:
  sys.stderr.write(p.stdout+p.stderr)
  raise SystemExit(p.returncode)
 print(p.stdout)
(base/'result.json').write_text(json.dumps({'source_sha256':source_sha256,'source_unchanged_during_run':hashlib.sha256(src.read_bytes()).hexdigest()==source_sha256,'status':'pass','scope':'Production Launcher/AppDelegate with dummy local worker, automatic startup disabled and sheet display intercepted; no real game/account/foreground UI','cases':['Store market persists in an isolated preference suite; invalid settings and active-operation changes are rejected; selected market reaches update worker arguments','100 repeated Cmd-Q calls create one sheet','real dummy worker playing-to-ready exit drains main-queue completion','sheet auto-dismisses when state changes or worker ends','Keep Open permits one fresh later prompt','stale completion cannot act on a fresh prompt','Stop Setup cancels real dummy process','checking/cancelling repeated quit guards','failed sign-out retries sign-out; successful ready/new resets to Play'],'limit':'Native sheet display needs separate interactive validation'},indent=2)+'\n')

if args.output: print('Evidence: '+str(base/'result.json'))
if workspace: workspace.cleanup()
