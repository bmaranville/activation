// sw.js

// Setup your project to serve `py-worker.js`. You should also serve
// `pyodide.js`, and all its associated `.asm.js`, `.data`, `.json`,
// and `.wasm` files as well:
importScripts("https://cdn.jsdelivr.net/npm/xhr-shim@0.1.3/src/index.js");
self.XMLHttpRequest = self.XMLHttpRequestShim;
importScripts("https://cdn.jsdelivr.net/pyodide/v0.20.0/full/pyodide.js");


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

self.addEventListener("install", async () => {
  let pyodideReadyPromise = loadPyodideAndPackages();
  await pyodideReadyPromise;
  console.log("install finished from sw.js side");
})

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
  console.log("clients claimed");
});

self.addEventListener("fetch", (event) => {
  if (event.request.url.endsWith("/nact.py")) {
    event.respondWith(do_calculation(event));
  }
});

async function do_calculation(event) {
  try {
    const json_data = await event.request.text();
    let python = `
      request = json.loads('${json_data}')
      form = FakeFieldStorage(request)
      json.dumps(nact.cgi_call(form))
    `;
    let results = await self.pyodide.runPythonAsync(python);
    return new Response(results, { headers: { 'Content-Type': 'application/json' } });
  }
  catch (error) {
    const edata = JSON.stringify({ success: false, detail: {error: error.message }});
    return new Response(edata, {headers: {'Content-Type': 'application/json'}});
  }
}