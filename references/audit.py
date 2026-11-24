#!/usr/bin/env python3
"""Audita o servidor local e imprime JSON: VM, SO, IPs, runtimes instalados
(python/java/php) e serviços (vhosts httpd -> processo -> runtime usado).

Uso: sudo ./audit_server.py [--domain RECIM] [--vm-name ACAMAR] [-o saida.json]
Rode como root para o `ss -p` e o /proc enxergarem processos de todos os usuários.
"""
import argparse, glob, json, os, platform, re, socket, subprocess

KINDS = {
    "python": re.compile(r"^python[\d.]*$"),
    "java": re.compile(r"^java$"),
    "php": re.compile(r"^php(-fpm|-cgi)?[\d.]*$"),
}
VER_ARGS = {"python": "--version", "java": "-version", "php": "-v"}
VER_RE = {
    "python": r"Python (\S+)",
    "java": r'version "([^"]+)"',
    "php": r"PHP (\S+)",
}
GLOBS = {
    "python": ["/usr/bin/python*", "/usr/local/bin/python*", "/opt/*/bin/python*"],
    "java": ["/usr/bin/java", "/usr/lib/jvm/*/bin/java", "/usr/java/*/bin/java", "/opt/*/bin/java"],
    "php": ["/usr/bin/php*", "/usr/sbin/php-fpm*", "/opt/remi/php*/root/usr/bin/php",
            "/opt/remi/php*/root/usr/sbin/php-fpm*"],
}


def sh(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        return r.stdout + r.stderr
    except Exception:
        return ""


def kind_of(binary):
    base = os.path.basename(binary)
    for k, rx in KINDS.items():
        if rx.match(base):
            return k
    return None


def version_of(binary, kind):
    out = sh(f"'{binary}' {VER_ARGS[kind]}")
    m = re.search(VER_RE[kind], out)
    return m.group(1) if m else None


def os_info():
    d = {}
    with open("/etc/os-release") as f:
        for l in f:
            if "=" in l:
                k, v = l.strip().split("=", 1)
                d[k] = v.strip('"')
    return {
        "name": d.get("NAME", platform.system()),
        "version": d.get("VERSION_ID", ""),
        "architecture": platform.machine().replace("_", "-"),
    }


def ips():
    out = sh("ip -o -4 addr show scope global")
    return sorted(set(re.findall(r"inet (\d+\.\d+\.\d+\.\d+)/", out)),
                  key=lambda x: tuple(map(int, x.split("."))))


def installed_runtimes():
    res = {}
    for kind, pats in GLOBS.items():
        seen, items = set(), []
        for pat in pats:
            for p in sorted(glob.glob(pat)):
                real = os.path.realpath(p)
                if real in seen or not os.access(real, os.X_OK) or kind_of(p) != kind:
                    continue
                seen.add(real)
                v = version_of(real, kind)
                if v:
                    items.append({"version": v, "path": real})
        res[kind] = sorted(items, key=lambda i: i["version"])
    return res


def read_conf():
    files = []
    for pat in ("/etc/httpd/conf/*.conf", "/etc/httpd/conf.d/*.conf",
                "/etc/apache2/sites-enabled/*.conf"):
        files += glob.glob(pat)
    for fp in sorted(files):
        try:
            with open(fp) as f:
                yield fp, "".join(l for l in f if not l.lstrip().startswith("#"))
        except OSError:
            pass


def vhosts():
    res = []
    for fp, txt in read_conf():
        for m in re.finditer(r"<VirtualHost\s+([^:>\s]+):(\d+)>(.*?)</VirtualHost>", txt, re.S | re.I):
            ip, port, body = m.group(1), int(m.group(2)), m.group(3)
            sn = re.search(r"^\s*ServerName\s+(\S+)", body, re.M | re.I)
            px = re.search(r"^\s*ProxyPass\s+\S+\s+https?://[^:/\s]+:(\d+)", body, re.M | re.I)
            ssl = re.search(r"^\s*SSLEngine\s+on", body, re.M | re.I)
            res.append({
                "file": fp,
                "hostname": sn.group(1) if sn else None,
                "ip": ip, "port": port,
                "protocol": "HTTPS" if ssl or port == 443 else "HTTP",
                "proxy_target": int(px.group(1)) if px else None,
            })
    return res


def pid_tree(pid):
    """pid + descendentes (cobre scripts wrapper que lançam java/python)."""
    pids, queue = [], [pid]
    while queue and len(pids) < 50:
        p = queue.pop(0)
        pids.append(p)
        queue += sh(f"pgrep -P {p}").split()
    return pids


def inspect_port(port):
    """Retorna (path /opt/<nome>, runtime dict) do processo que escuta na porta."""
    m = re.search(r"pid=(\d+)", sh(f"ss -ltnpH 'sport = :{port}'"))
    if not m:
        return None, None
    path, runtime = None, None
    for pid in pid_tree(m.group(1)):
        try:
            with open(f"/proc/{pid}/cmdline") as f:
                txt = f.read().replace("\0", " ") + " " + os.readlink(f"/proc/{pid}/cwd")
            exe = os.path.realpath(f"/proc/{pid}/exe")
        except OSError:
            continue
        if not path:
            p = re.search(r"(/opt/[^/\s]+)", txt)
            path = p.group(1) if p else None
        k = kind_of(exe)
        if k and not runtime:
            runtime = {"type": k, "version": version_of(exe, k), "binary": exe, "detected_by": "process"}
    return path, runtime


def runtime_from_files(path):
    """Fallback quando não há processo: deduz o tipo pelos arquivos do projeto."""
    if not path:
        return None
    def has(*pats):
        return any(glob.glob(os.path.join(path, p)) for p in pats)
    if has("pom.xml", "build.gradle*", "*.jar", "target/*.jar"):
        return {"type": "java", "version": None, "binary": None, "detected_by": "files"}
    if has("requirements.txt", "pyproject.toml", "venv/pyvenv.cfg", ".venv/pyvenv.cfg", "*.py"):
        ver = None
        for cfg in glob.glob(os.path.join(path, "*venv*/pyvenv.cfg")):
            m = re.search(r"^version\s*=\s*(\S+)", open(cfg).read(), re.M)
            ver = m.group(1) if m else None
        return {"type": "python", "version": ver, "binary": None, "detected_by": "files"}
    if has("composer.json", "*.php"):
        return {"type": "php", "version": None, "binary": None, "detected_by": "files"}
    return None


def services():
    out = []
    for v in vhosts():
        if not v["hostname"] or v["proxy_target"] is None:
            continue
        path, runtime = inspect_port(v["proxy_target"])
        runtime = runtime or runtime_from_files(path)
        name = os.path.basename(path) if path else os.path.splitext(os.path.basename(v["file"]))[0]
        out.append({
            "name": name,
            "path": path,
            "runtime": runtime,
            "virtual_host": {k: v[k] for k in ("hostname", "ip", "port", "protocol", "proxy_target")},
        })
    return sorted(out, key=lambda s: s["name"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain")
    ap.add_argument("--vm-name")
    ap.add_argument("-o", "--output")
    a = ap.parse_args()

    host = socket.gethostname().split(".")[0]
    data = {
        "vm_name": a.vm_name or host.upper(),
        "hostname": host,
        "domain": a.domain or sh("dnsdomainname").strip() or None,
        "operating_system": os_info(),
        "ips": ips(),
        "installed_runtimes": installed_runtimes(),
        "services": services(),
    }
    js = json.dumps(data, indent=4, ensure_ascii=False)
    if a.output:
        with open(a.output, "w") as f:
            f.write(js + "\n")
    else:
        print(js)


if __name__ == "__main__":
    main()