// webworker.js

// Setup your project to serve `py-worker.js`. You should also serve
// `pyodide.js`, and all its associated `.asm.js`, `.data`, `.json`,
// and `.wasm` files as well:
importScripts("https://cdn.jsdelivr.net/pyodide/v0.29.3/full/pyodide.js");
// importScripts("./pyodide/pyodide.js");

async function loadPyodideAndPackages() {
  self.pyodide = await loadPyodide();
  await self.pyodide.loadPackage(["numpy", "pytz", "micropip"]);
  await self.pyodide.runPythonAsync(`
    import micropip
    await micropip.install("periodictable")
    import periodictable
    print(periodictable.__version__)
  `)

  // Downloading a single file
  await pyodide.runPythonAsync(`
    from pyodide.http import pyfetch
    response = await pyfetch("../cgi-bin/nact.py")
    with open("nact.py", "wb") as f:
        f.write(await response.bytes())
    import nact
    import json
    import re

    class FakeFieldStorage(dict):
        def getfirst(self, name, default=None):
            rval = self.get(name, default)
            return rval if rval != "" else default
        def getlist(self, name, default=None):
            name = re.sub("\\[\\]$", "", name)
            rval = self.get(name, default)
            if isinstance(rval, str) or isinstance(rval, bytes):
                return [rval]
            return list(rval)
  `)
}
let pyodideReadyPromise = loadPyodideAndPackages();
pyodideReadyPromise.then(() => self.postMessage({worker_ready: true}));

self.onmessage = async (event) => {
  // make sure loading is done
  await pyodideReadyPromise;
  // Don't bother yet with this line, suppose our API is built in such a way:
  const { request } = event.data;
  const json_data = JSON.stringify(event.data.data);
  // Now is the easy part, the one that is similar to working in the main thread:
  try {
    let python = `
      request = json.loads('${json_data}')
      form = FakeFieldStorage(request)
      json.dumps(nact.cgi_call(form))
    `;
    //console.log('python:', python);
    let results = await self.pyodide.runPythonAsync(python);
    let ldata = JSON.parse(results);
    self.postMessage(ldata);
  } catch (error) {
    self.postMessage({ success: false, detail: {error: error.message }});
  }
};