# Optional: remote access over Tailscale

H3 Studio is local-only by default. If you want to use it from your phone or another computer, the recommended way is **Tailscale Serve**:
your Mac keeps listening on `127.0.0.1`; Tailscale adds an HTTPS endpoint that only devices in *your* tailnet can reach.

```bash
bin/h3studio tailscale-on          # HTTPS on tailnet port 8443 -> http://127.0.0.1:8195, enables secure cookies
bin/h3studio restart
# -> https://<this-mac>.<your-tailnet>.ts.net:8443
bin/h3studio tailscale-off         # remove the mapping, disable secure cookies
```

What the commands do and don't do:

* They use `tailscale serve` only. **Never use `tailscale funnel`:** it publishes the service on the public internet.
* `tailscale-on` refuses to run if that HTTPS port already has a mapping, so it cannot overwrite your other services. Pick another port with `tailscale-on 9443`.
* If your `tailscaled` uses a non-default socket (userspace mode, custom state dir): `TS_SOCKET=/path/tailscaled.sock bin/h3studio tailscale-on`.
* Access is then controlled by your tailnet ACLs **and** the H3 Studio password. If other people share your tailnet, add the allow-list described in [`SECURITY-MODEL.md`](SECURITY-MODEL.md).
* A Mac cannot always reach its *own* tailnet address (userspace networking); test from another device.

Installing the PWA ("安装" button) needs HTTPS or `localhost`, so the Tailscale address is the way to install it on a phone.

Other ways (a reverse proxy, port forwarding, LAN exposure) are possible but not supported or recommended: there is no TLS or account system built in.
