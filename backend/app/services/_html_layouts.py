"""
Static HTML layout methods for generating diverse UI mockup prototypes.

Each method returns HTML with four <section class="view"> blocks (data-view
main/list/detail/settings) using the provided CSS variable strings. These
are designed to be called from UiVisualizer._generate_html() and plugged
into its f-string template.

The caller applies layout-specific CSS overrides so each layout type
appears visually distinct — not just different text in the same skeleton.
"""

from __future__ import annotations

import hashlib
from typing import Final


class HtmlLayouts:
    """Static methods that generate unique HTML layouts for different UI types.

    Every method accepts the same colour/style arguments so the caller
    (UiVisualizer._generate_html) can dispatch uniformly.  Content varies
    deterministically by ``project_name`` so the same spec always produces
    the same mockup.
    """

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _int_from_name(project_name: str, salt: str = "", modulus: int = 100) -> int:
        """Deterministic integer in [0, modulus) from project_name + optional salt."""
        h = hashlib.md5((project_name + salt).encode()).hexdigest()
        return int(h[:8], 16) % modulus

    @staticmethod
    def _pick(items: tuple[str, ...], project_name: str, salt: str = "") -> str:
        """Pick an item from *items* deterministically."""
        idx = HtmlLayouts._int_from_name(project_name, salt, len(items))
        return items[idx]

    # ═════════════════════════════════════════════════════════════════
    #  Chat layout sub-builders (extracted to avoid nested f-string
    #  expressions that Python 3.9 cannot parse).
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def _build_chat_conv_items(
        chats: list, primary: str, secondary: str, surface: str,
        border: str, text_color: str, text_muted: str,
    ) -> str:
        parts: list[str] = []
        colors = [primary, secondary, primary, secondary, primary, secondary]
        for i, (name, msg, online, unread) in enumerate(chats):
            bg = "transparent" if i != 0 else primary + "10"
            fw = 600 if unread > 0 else 400
            tc = text_color if unread > 0 else text_muted
            dot = f'<span style="font-weight:600;color:{primary}">{chr(183)}{unread}</span>' if unread > 0 else ""
            parts.append(
                f'<div style="display:flex;gap:10px;padding:12px;cursor:pointer;'
                f'border-bottom:1px solid {border};background:{bg};transition:background 0.15s">'
                f'<div class="avatar" style="width:40px;height:40px;font-size:15px;'
                f'min-width:40px;background:{colors[i]}">{name[0]}</div>'
                f'<div style="flex:1;min-width:0">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span style="font-size:14px;font-weight:{fw}">{name}</span>'
                f'<span style="font-size:11px;color:{text_muted}">{10 - i}m</span></div>'
                f'<div style="font-size:12px;color:{tc};white-space:nowrap;overflow:hidden;'
                f'text-overflow:ellipsis;margin-top:2px">{msg}{dot}</div>'
                f'</div></div>'
            )
        return "\n".join(parts)

    @staticmethod
    def _build_chat_bubbles(
        primary: str, secondary: str, input_bg: str,
        text_color: str, text_muted: str, n: int,
    ) -> str:
        messages = [
            "Hey team, the new dashboard is ready for review on staging. Can someone take a look?",
            "Sure, I'll check it out after standup. Any known issues?",
            "Just the mobile responsiveness on the stats page " + chr(8212) + " working on a fix now.",
            "Great, I'll review in 30 mins. Let me know if you need help with the CSS.",
            "Actually could we push the release to Friday? Want to run more tests.",
            "Friday works for me. Let's update the milestone. Would also love to add the chart animations.",
        ]
        parts: list[str] = []
        for i, msg in enumerate(messages):
            is_me = i % 3 == 2
            parts.append(
                f'<div style="display:flex;gap:8px;'
                f'{"flex-direction:row-reverse" if is_me else ""};align-items:flex-start">'
                f'<div class="avatar" style="width:28px;height:28px;font-size:11px;'
                f'min-width:28px;background:{primary if is_me else secondary}">'
                f'{"Y" if is_me else "M" if i % 2 == 0 else "J"}</div>'
                f'<div style="max-width:70%;padding:10px 14px;'
                f'border-radius:{"14px 14px 4px 14px" if is_me else "14px 14px 14px 4px"};'
                f'background:{primary if is_me else input_bg};'
                f'color:{"#fff" if is_me else text_color};font-size:13px;line-height:1.5">'
                f'{msg}'
                f'<div style="font-size:10px;color:{text_muted};margin-top:4px;text-align:right">'
                f'10:{(n + i * 3) % 60:02d} AM</div></div></div>'
            )
        return "\n".join(parts)

    @staticmethod
    def _build_chat_table_rows(
        chats: list, primary: str, text_muted: str, n: int,
    ) -> str:
        parts: list[str] = []
        for i, (name, msg, online, unread) in enumerate(chats):
            unread_cell = (
                f'<span class="badge" style="background:{primary};color:white;font-size:12px">'
                f'{unread}</span>'
                if unread > 0
                else f'<span style="color:{text_muted}">0</span>'
            )
            parts.append(
                f'<tr><td style="font-weight:500">{name}</td>'
                f'<td style="color:{text_muted};max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
                f'{msg[:50]}</td>'
                f'<td>{unread_cell}</td>'
                f'<td style="color:{text_muted}">{(n + i * 3) % 8 + 2}</td>'
                f'<td style="color:{text_muted}">{10 - i}m ago</td></tr>'
            )
        return "\n".join(parts)

    @staticmethod
    def _build_chat_member_items(
        names: list, primary: str, secondary: str,
        input_bg: str, border: str, surface: str, n: int,
    ) -> str:
        parts: list[str] = []
        for i in range(n % 5 + 3):
            color = primary if i % 2 == 0 else secondary
            parts.append(
                f'<div style="display:flex;align-items:center;gap:8px;padding:8px 14px;'
                f'border-radius:8px;border:1px solid {border};background:{input_bg}">'
                f'<span class="avatar" style="width:24px;height:24px;font-size:10px;'
                f'min-width:24px;background:{color}">{names[i][0]}</span>'
                f'<span style="font-size:13px">{names[i]}</span>'
                f'<span style="font-size:11px;color:{secondary}">{chr(9679)}</span></div>'
            )
        return "\n".join(parts)

    # ═════════════════════════════════════════════════════════════════
    #  1. Dashboard
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def _layout_dashboard(
        primary: str,
        secondary: str,
        surface: str,
        text_color: str,
        text_muted: str,
        border: str,
        border_strong: str,
        input_bg: str,
        is_dark: bool,
        project_name: str,
    ) -> str:
        n = HtmlLayouts._int_from_name(project_name, "dash", 100)
        users = 1200 + n * 47
        revenue = 45200 + n * 312
        orders = 340 + n * 8
        conversions = 2.1 + (n % 10) * 0.32
        chart_pct = 30 + (n % 60)

        product_list = [
            ("CloudSync Pro", f"${19.99 + (n % 5) * 5:.2f}", conversions * 0.6),
            ("DataVault Enterprise", f"${89.99 + (n % 3) * 20:.2f}", conversions * 0.3),
            ("API Gateway Standard", f"${49.99 + (n % 4) * 10:.2f}", conversions * 0.45),
        ]

        return f"""<section class="view active" data-view="main">
  <div class="header-row">
    <h1>📊 {project_name or 'Dashboard'}</h1>
    <div>
      <button class="btn btn-outline">📥 Export</button>
      <button class="btn btn-primary" style="margin-left:8px">+ New Report</button>
    </div>
  </div>
  <div class="stats">
    <div class="stat-card">
      <div class="label">Total Users</div>
      <div class="value" style="color:{primary}">{users:,}</div>
      <div style="font-size:12px;color:{text_muted};margin-top:6px">+{n % 20}% this week</div>
    </div>
    <div class="stat-card">
      <div class="label">Revenue</div>
      <div class="value" style="color:{secondary}">${revenue:,}</div>
      <div style="font-size:12px;color:{text_muted};margin-top:6px">{'+' if n % 2 == 0 else ''}{(n % 15) - 5}% vs last month</div>
    </div>
    <div class="stat-card">
      <div class="label">Orders</div>
      <div class="value" style="color:{primary}">{orders:,}</div>
      <div style="font-size:12px;color:{text_muted};margin-top:6px">{n % 30} pending</div>
    </div>
    <div class="stat-card">
      <div class="label">Conversion</div>
      <div class="value" style="color:{secondary}">{conversions:.1f}%</div>
      <div style="font-size:12px;color:{text_muted};margin-top:6px">{'↑' if n % 3 == 0 else '↓'} {n % 10}% change</div>
    </div>
  </div>
  <div class="card-grid">
    <div class="card" style="grid-column:1/-1">
      <h3>📈 Monthly Performance</h3>
      <p style="color:{text_muted};margin-bottom:16px">Revenue & user growth over the last 6 months</p>
      <div class="chart-placeholder" style="height:200px;background:linear-gradient(135deg,{primary}20,{secondary}30);border:1px solid {border};border-radius:10px;display:flex;align-items:flex-end;padding:16px 24px;gap:8px">
        {''.join(f'<div style="flex:1;background:{primary};height:{30+(i*7)+(n%20)}%;border-radius:4px 4px 0 0;min-width:24px;opacity:{0.5+i*0.08:.1f}" title="Month {i+1}"></div>' for i in range(12))}
      </div>
    </div>
  </div>
  <div class="card-grid" style="margin-top:16px">
    <div class="card">
      <h3>🔥 Top Products</h3>
{"".join(f'    <div style="display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid {border};font-size:14px"><span>{name}</span><span style="color:{primary};font-weight:600">{price}</span><span style="color:{text_muted};font-size:12px">{int(sold)} sold</span></div>' for name, price, sold in product_list)}
    </div>
    <div class="card">
      <h3>⚡ Quick Actions</h3>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:12px">
        <span class="badge">📦 New Order</span>
        <span class="badge">👤 Add User</span>
        <span class="badge">📄 Generate Report</span>
        <span class="badge">🔔 Send Notification</span>
        <span class="badge">⚙️ Run Backup</span>
      </div>
    </div>
  </div>
</section>

<section class="view" data-view="list">
  <div class="header-row">
    <h1>📋 All Records</h1>
    <input type="text" placeholder="Search records..." style="padding:8px 14px;border-radius:8px;border:1px solid {border_strong};background:{input_bg};color:{text_color};width:260px;font-size:14px;font-family:inherit">
  </div>
  <table class="list-table">
    <thead>
      <tr><th>Name</th><th>Status</th><th>Progress</th><th>Assigned To</th><th>Due Date</th></tr>
    </thead>
    <tbody>
{''.join(f'      <tr><td style="font-weight:500">{item}</td><td><span class="badge{"-ok" if i%3==0 else "-warn" if i%3==1 else ""}">{["Active","Pending","Review"][i%3]}</span></td><td><div class="progress"><span style="width:{(n+i*13)%100}%"></span></div></td><td style="color:{text_muted}">{"Alice Chen,Bob Liu,Cara Diaz,Eve Park,Fred Wu".split(",")[i%5]}</td><td style="color:{text_muted}">2026-{(i%12)+1:02d}-{(i%28)+1:02d}</td></tr>' for i, item in enumerate(["User Auth Module","Payment Gateway","Analytics Dashboard","Notification Service","Data Export Pipeline","Search Index","Cache Layer","API Versioning"]))}
    </tbody>
  </table>
</section>

<section class="view" data-view="detail">
  <div class="header-row">
    <h1>🔍 {product_list[0][0]}</h1>
    <span class="badge badge-ok">Active</span>
  </div>
  <div class="card-grid">
    <div class="card">
      <h3>Description</h3>
      <p style="color:{text_muted};font-size:14px;margin-top:8px">
        {project_name or 'This product'} provides comprehensive cloud synchronization
        capabilities with end-to-end encryption, real-time collaboration,
        and cross-platform support. Version {n % 10}.{n % 6}.0 released
        with performance improvements and bug fixes.
      </p>
      <div style="margin-top:16px;padding-top:16px;border-top:1px solid {border}">
        <div class="form-row"><label>Product ID</label><span style="color:{text_muted}">PRD-{1000+n:04d}</span></div>
        <div class="form-row"><label>Created</label><span style="color:{text_muted}">2026-{(n%12)+1:02d}-{(n%28)+1:02d}</span></div>
        <div class="form-row"><label>Category</label><span style="color:{text_muted}>{['SaaS','Infrastructure','Analytics','Developer Tools'][n%4]}</span></div>
      </div>
    </div>
    <div class="card">
      <h3>Activity Log</h3>
      <div style="margin-top:12px">
{"".join(f'      <div style="display:flex;gap:12px;padding:8px 0;border-bottom:1px solid {border};font-size:13px"><span style="color:{primary};font-weight:600">{["Updated","Created","Reviewed","Deployed","Approved"][i%5]}</span><span style="color:{text_muted};flex:1">{["Settings page redesigned","API endpoint added","Code review completed","v{n%10}.{n%6}.0 deployed to staging","PR #{(100+n*3+i)%999} merged"][i%5]}</span><span style="color:{text_muted};font-size:12px">{10-i}h ago</span></div>' for i in range(5))}
      </div>
    </div>
  </div>
</section>

<section class="view" data-view="settings">
  <div class="header-row"><h1>⚙️ Dashboard Settings</h1></div>
  <div style="background:{surface};border-radius:12px;border:1px solid {border};padding:24px">
    <div class="form-row">
      <label>Widget Layout</label>
      <select><option>Grid (4 columns)</option><option>Grid (3 columns)</option><option>List</option></select>
    </div>
    <div class="form-row">
      <label>Default Time Range</label>
      <select><option>Last 7 days</option><option>Last 30 days</option><option>Last quarter</option></select>
    </div>
    <div class="form-row">
      <label>Auto-Refresh</label>
      <select><option>Every 30 seconds</option><option>Every 5 minutes</option><option>Disabled</option></select>
    </div>
    <div class="form-row">
      <label>Metric Units</label>
      <select><option>Thousands (K)</option><option>Millions (M)</option><option>Exact</option></select>
    </div>
    <div class="form-row" style="border-bottom:none;padding-bottom:0">
      <label></label>
      <button class="btn btn-primary">Save Preferences</button>
    </div>
  </div>
</section>
"""

    # ═════════════════════════════════════════════════════════════════
    #  2. Landing Page
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def _layout_landing_page(
        primary: str,
        secondary: str,
        surface: str,
        text_color: str,
        text_muted: str,
        border: str,
        border_strong: str,
        input_bg: str,
        is_dark: bool,
        project_name: str,
    ) -> str:
        n = HtmlLayouts._int_from_name(project_name, "landing", 100)
        headline = HtmlLayouts._pick(
            ("Build Smarter. Ship Faster.",
             "Transform Your Workflow Today",
             "The Future of {0} Is Here",
             "Empower Your Team With {0}",
             "Next-Gen {0} Platform"),
            project_name, "headline",
        ).format(project_name or "Product")

        subtitle = HtmlLayouts._pick(
            ("Enterprise-grade platform designed for modern teams to collaborate seamlessly.",
             "Unlock your team's full potential with AI-powered tools and real-time insights.",
             "From idea to production in record time — no complex setup required.",
             "Thousands of companies trust {0} to deliver exceptional results every day.",
             "The all-in-one solution that grows with your business."),
            project_name, "subtitle",
        ).format(project_name or "our platform")

        # active_users for the CTA section
        active_users = (n + 1) * 1200

        return f"""<section class="view active" data-view="main">
  <div style="text-align:center;padding:60px 40px 40px">
    <h1 style="font-size:42px;font-weight:800;line-height:1.15;margin-bottom:16px;letter-spacing:-0.5px">
      {headline}
    </h1>
    <p style="font-size:18px;color:{text_muted};max-width:620px;margin:0 auto 32px;line-height:1.6">
      {subtitle}
    </p>
    <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap">
      <button class="btn btn-primary" style="padding:12px 32px;font-size:16px">🚀 Get Started Free</button>
      <button class="btn btn-outline" style="padding:12px 32px;font-size:16px">▶ Watch Demo</button>
    </div>
    <div style="margin-top:40px;display:flex;justify-content:center;gap:48px;flex-wrap:wrap;padding:24px 0;border-top:1px solid {border}">
      <div style="text-align:center"><div style="font-size:28px;font-weight:700;color:{primary}">{(n+1)*1200:,}</div><div style="font-size:13px;color:{text_muted}">Active Users</div></div>
      <div style="text-align:center"><div style="font-size:28px;font-weight:700;color:{secondary}">{n*35+50:,}</div><div style="font-size:13px;color:{text_muted}">Enterprise Clients</div></div>
      <div style="text-align:center"><div style="font-size:28px;font-weight:700;color:{primary}">99.{n%10}%</div><div style="font-size:13px;color:{text_muted}">Uptime SLA</div></div>
      <div style="text-align:center"><div style="font-size:28px;font-weight:700;color:{secondary}">{n+4}.{n%6}</div><div style="font-size:13px;color:{text_muted}">Avg. Rating</div></div>
    </div>
  </div>
  <h2 style="font-size:22px;font-weight:700;margin:0 0 20px;padding:0 24px">Why Choose {project_name or 'Us'}?</h2>
  <div class="card-grid" style="padding:0 24px">
    {''.join(f'    <div class="card" style="padding:28px"><div style="font-size:32px;margin-bottom:12px">{emoji}</div><h3 style="font-size:17px;margin-bottom:8px">{title}</h3><p style="font-size:14px;color:{text_muted};line-height:1.6">{desc}</p></div>' for emoji, title, desc in [("⚡", "Lightning Fast", "Sub-millisecond response times with our global edge network."),("🔒", "Enterprise Security", "SOC 2 Type II certified with end-to-end encryption, RBAC, and audit logging."),("🤖", "AI-Powered", "Smart automation and predictive analytics that learn from your workflows.")])}
  </div>
  <div style="margin-top:32px;text-align:center;padding:40px 24px;background:{primary}10;border-radius:12px;margin-left:24px;margin-right:24px">
    <h2 style="font-size:24px;font-weight:700;margin-bottom:8px">Ready to Get Started?</h2>
    <p style="color:{text_muted};margin-bottom:20px;font-size:15px">Join {active_users:,}+ users already on the platform</p>
    <button class="btn btn-primary" style="padding:12px 36px;font-size:16px">Start Free Trial →</button>
  </div>
</section>

<section class="view" data-view="list">
  <div class="header-row">
    <h1>📄 All Features</h1>
  </div>
  <table class="list-table">
    <thead>
      <tr><th>Feature</th><th>Category</th><th>Availability</th><th>Documentation</th></tr>
    </thead>
    <tbody>
{''.join(f'      <tr><td style="font-weight:500">{feat}</td><td style="color:{text_muted}">{cat}</td><td><span class="badge badge-ok">{avail}</span></td><td style="color:{primary};cursor:pointer">View Docs →</td></tr>' for feat, cat, avail in [
    ("Real-time Collaboration", "Productivity", "All Plans"),
    ("Custom Workflows", "Automation", "Pro + Enterprise"),
    ("Advanced Analytics", "Insights", "Enterprise"),
    ("API Access", "Integration", "All Plans"),
    ("SSO / SAML", "Security", "Enterprise"),
    ("Audit Logs", "Compliance", "Enterprise"),
    ("Role-based Access", "Security", "Pro + Enterprise"),
    ("Webhook Integrations", "Integration", "All Plans"),
])}
    </tbody>
  </table>
</section>

<section class="view" data-view="detail">
  <div class="header-row">
    <h1>🔍 Lightning Fast</h1>
    <button class="btn btn-outline">📚 View Full Docs</button>
  </div>
  <div style="background:{surface};border-radius:12px;border:1px solid {border};padding:24px">
    <h3 style="font-size:18px;margin-bottom:12px">Sub-millisecond response times with global edge network...</h3>
    <p style="color:{text_muted};font-size:14px;line-height:1.7">
      {project_name or 'Our platform'} leverages global edge nodes deployed across {15+n} regions
      to ensure sub-millisecond response times for every request. Caching layers at the CDN, application,
      and database levels minimize latency. Built-in load balancing and auto-scaling handle traffic
      spikes without manual intervention.
    </p>
    <h4 style="margin-top:20px;margin-bottom:10px">Key Metrics</h4>
    <div class="stats" style="grid-template-columns:repeat(3,1fr)">
      <div class="stat-card"><div class="label">Avg. Latency</div><div class="value" style="font-size:20px;color:{primary}">{12+n%20}ms</div></div>
      <div class="stat-card"><div class="label">Requests / Day</div><div class="value" style="font-size:20px;color:{secondary}">{(n+1)*50000:,}</div></div>
      <div class="stat-card"><div class="label">Cache Hit Rate</div><div class="value" style="font-size:20px;color:{primary}">{85+n%10}%</div></div>
    </div>
  </div>
</section>

<section class="view" data-view="settings">
  <div class="header-row"><h1>⚙️ Landing Page Settings</h1></div>
  <div style="background:{surface};border-radius:12px;border:1px solid {border};padding:24px">
    <div class="form-row">
      <label>Hero Headline</label>
      <input type="text" value="{headline[:40]}" style="width:100%">
    </div>
    <div class="form-row">
      <label>CTA Button Text</label>
      <input type="text" value="Get Started Free">
    </div>
    <div class="form-row">
      <label>Show Stats Bar</label>
      <select><option>Enabled</option><option>Disabled</option></select>
    </div>
    <div class="form-row">
      <label>Feature Cards Layout</label>
      <select><option>3-column grid</option><option>2-column grid</option><option>List</option></select>
    </div>
    <div class="form-row">
      <label>Social Proof Banner</label>
      <select><option>Show testimonials</option><option>Show logo cloud</option><option>Hidden</option></select>
    </div>
    <div class="form-row" style="border-bottom:none;padding-bottom:0">
      <label></label>
      <button class="btn btn-primary">Save Changes</button>
    </div>
  </div>
</section>
"""

    # ═════════════════════════════════════════════════════════════════
    #  3. Kanban Board
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def _layout_kanban_board(
        primary: str,
        secondary: str,
        surface: str,
        text_color: str,
        text_muted: str,
        border: str,
        border_strong: str,
        input_bg: str,
        is_dark: bool,
        project_name: str,
    ) -> str:
        n = HtmlLayouts._int_from_name(project_name, "kanban", 100)

        todo_tasks = [
            ("Design system migration", f"#{800+n}"),
            ("API rate limit refactor", f"#{700+n}"),
            ("User onboarding v2", f"#{600+n}"),
            ("Dark mode support", f"#{500+n}"),
            ("Mobile responsive fixes", f"#{400+n}"),
        ]
        inprog_tasks = [
            ("Payment integration", f"#{300+n}"),
            ("Search autocomplete", f"#{200+n}"),
            ("Notification center", f"#{100+n}"),
        ]
        done_tasks = [
            ("Login page redesign", f"#{(n+50)%100+800}"),
            ("Database migration", f"#{(n+40)%100+700}"),
            ("Unit test coverage", f"#{(n+30)%100+600}"),
            ("Build pipeline v2", f"#{(n+20)%100+500}"),
        ]

        members = ["Alice", "Bob", "Carol", "Dave", "Eve"]

        return f"""<section class="view active" data-view="main">
  <div class="header-row">
    <h1>📋 {project_name or 'Kanban'} Board</h1>
    <div>
      <button class="btn btn-outline">🔍 Filter</button>
      <button class="btn btn-primary" style="margin-left:8px">+ Add Task</button>
    </div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px">
    <!-- To Do -->
    <div style="background:{input_bg};border-radius:12px;border:1px solid {border};padding:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <h3 style="font-size:15px;font-weight:600">📝 To Do <span style="color:{text_muted};font-size:12px;font-weight:400">({len(todo_tasks)})</span></h3>
        <span class="badge badge-warn">{n%5+2} due soon</span>
      </div>
{"".join(f'      <div style="background:{surface};border-radius:10px;border:1px solid {border};padding:14px;margin-bottom:10px;cursor:pointer">'
        f'<div style="display:flex;justify-content:space-between;margin-bottom:8px">'
        f'<span style="font-size:13px;font-weight:500">{task}</span>'
        f'<span style="font-size:11px;color:{text_muted}">{ref}</span>'
        f'</div>'
        f'<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">'
        f'<span class="badge" style="background:{primary}15;color:{primary};font-size:11px">{["frontend","backend","design","devops","docs"][i%5]}</span>'
        f'<span class="badge badge-warn" style="font-size:11px">{"high" if i<2 else "medium"}</span>'
        f'</div>'
        f'<div style="display:flex;align-items:center;gap:6px">'
        f'<span class="avatar" style="width:26px;height:26px;font-size:11px;background:{primary}">{members[i%5][0]}</span>'
        f'<span style="font-size:12px;color:{text_muted}">{members[i%5]}</span>'
        f'</div>'
        f'</div>' for i, (task, ref) in enumerate(todo_tasks))}
    </div>
    <!-- In Progress -->
    <div style="background:{input_bg};border-radius:12px;border:1px solid {border};padding:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <h3 style="font-size:15px;font-weight:600">🔄 In Progress <span style="color:{text_muted};font-size:12px;font-weight:400">({len(inprog_tasks)})</span></h3>
        <span class="badge badge-ok">{n%2+1} today</span>
      </div>
{"".join(f'      <div style="background:{surface};border-radius:10px;border:1px solid {border};padding:14px;margin-bottom:10px;cursor:pointer">'
        f'<div style="display:flex;justify-content:space-between;margin-bottom:8px">'
        f'<span style="font-size:13px;font-weight:500">{task}</span>'
        f'<span style="font-size:11px;color:{text_muted}">{ref}</span>'
        f'</div>'
        f'<div class="progress" style="margin-bottom:8px"><span style="width:{(n+30+i*25)%95+5}%"></span></div>'
        f'<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">'
        f'<span class="badge" style="background:{secondary}15;color:{secondary};font-size:11px">{["backend","frontend","fullstack","infra"][i%4]}</span>'
        f'</div>'
        f'<div style="display:flex;align-items:center;gap:6px">'
        f'<span class="avatar" style="width:26px;height:26px;font-size:11px;background:{secondary}">{members[(i+2)%5][0]}</span>'
        f'<span style="font-size:12px;color:{text_muted}">{members[(i+2)%5]}</span>'
        f'</div>'
        f'</div>' for i, (task, ref) in enumerate(inprog_tasks))}
    </div>
    <!-- Done -->
    <div style="background:{input_bg};border-radius:12px;border:1px solid {border};padding:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
        <h3 style="font-size:15px;font-weight:600">✅ Done <span style="color:{text_muted};font-size:12px;font-weight:400">({len(done_tasks)})</span></h3>
      </div>
{"".join(f'      <div style="background:{surface};border-radius:10px;border:1px solid {border};padding:14px;margin-bottom:10px;opacity:0.75">'
        f'<div style="display:flex;justify-content:space-between;margin-bottom:8px">'
        f'<span style="font-size:13px;font-weight:500;text-decoration:line-through;text-decoration-color:{text_muted}">{task}</span>'
        f'<span style="font-size:11px;color:{text_muted}">{ref}</span>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;align-items:center">'
        f'<span class="badge badge-ok" style="font-size:11px">✔ Done</span>'
        f'<span style="font-size:11px;color:{text_muted}">{n+i}d ago</span>'
        f'</div>'
        f'</div>' for i, (task, ref) in enumerate(done_tasks))}
    </div>
  </div>
</section>

<section class="view" data-view="list">
  <div class="header-row">
    <h1>📋 All Tasks</h1>
    <input type="text" placeholder="Search tasks..." style="padding:8px 14px;border-radius:8px;border:1px solid {border_strong};background:{input_bg};color:{text_color};width:240px;font-size:14px;font-family:inherit">
  </div>
  <table class="list-table">
    <thead>
      <tr><th>Task</th><th>Status</th><th>Priority</th><th>Assignee</th><th>Labels</th></tr>
    </thead>
    <tbody>
{''.join(f'      <tr><td style="font-weight:500">{t}</td><td><span class="badge{"-ok" if st=="Done" else "-warn" if st=="In Progress" else ""}">{st}</span></td><td style="color:{"#ef4444" if p=="High" else "#f59e0b" if p=="Medium" else text_muted}">{p}</td><td style="color:{text_muted}">{members[i%5]}</td><td><span class="badge" style="background:{primary}15;color:{primary};font-size:11px">{["bug","feature","chore","docs","perf"][i%5]}</span></td></tr>' for i, (t, st, p) in enumerate([("Design system migration","To Do","High"),("API rate limit refactor","To Do","High"),("Payment integration","In Progress","Medium"),("Search autocomplete","In Progress","Medium"),("Login page redesign","Done","Low"),("Database migration","Done","Medium"),("Notification center","In Progress","High"),("Mobile responsive fixes","To Do","Low"),("Unit test coverage","Done","Medium"),("Build pipeline v2","Done","Low")]))}
    </tbody>
  </table>
</section>

<section class="view" data-view="detail">
  <div class="header-row">
    <h1>🔍 {inprog_tasks[0][0]}</h1>
    <span class="badge badge-warn">In Progress</span>
  </div>
  <div style="background:{surface};border-radius:12px;border:1px solid {border};padding:24px">
    <div style="display:flex;gap:24px;margin-bottom:20px;flex-wrap:wrap">
      <div><span style="color:{text_muted};font-size:12px">Assignee</span><div style="display:flex;align-items:center;gap:8px;margin-top:4px"><span class="avatar" style="width:32px;height:32px;font-size:13px;background:{primary}">{members[(n)%5][0]}</span><span style="font-weight:500">{members[(n)%5]}</span></div></div>
      <div><span style="color:{text_muted};font-size:12px">Due Date</span><div style="font-weight:500;margin-top:4px">2026-{(n%12)+1:02d}-{(n%28)+1:02d}</div></div>
      <div><span style="color:{text_muted};font-size:12px">Priority</span><div style="font-weight:500;color:#ef4444;margin-top:4px">High</div></div>
    </div>
    <h4 style="margin-bottom:8px">Description</h4>
    <p style="color:{text_muted};font-size:14px;line-height:1.7">
      Implement a robust {project_name or 'payment'} integration supporting Stripe, PayPal, and
      local payment methods. Includes webhook handling, idempotency keys, refund flow,
      and receipt generation. Estimated effort: {n%8+3} story points.
    </p>
    <h4 style="margin:16px 0 8px">Subtasks</h4>
{"".join(f'    <div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid {border};font-size:14px"><input type="checkbox" {"checked" if i%3==0 else ""} style="accent-color:{primary}"><span style="{"text-decoration:line-through;text-decoration-color:"+text_muted if i%3==0 else ""};color:{text_muted if i%3==0 else text_color}">{sub}</span></div>' for i, sub in enumerate(["Design database schema","Implement Stripe webhook","Add PayPal SDK","Write refund API endpoint","Create receipt template","Add idempotency key handling","Write integration tests"]))}
  </div>
</section>

<section class="view" data-view="settings">
  <div class="header-row"><h1>⚙️ Board Settings</h1></div>
  <div style="background:{surface};border-radius:12px;border:1px solid {border};padding:24px">
    <div class="form-row">
      <label>Board Name</label>
      <input type="text" value="{project_name or 'Kanban'} Board">
    </div>
    <div class="form-row">
      <label>Columns</label>
      <select><option>To Do / In Progress / Done</option><option>Backlog / To Do / In Progress / Review / Done</option><option>To Do / Doing / Done</option></select>
    </div>
    <div class="form-row">
      <label>Auto-archive done tasks</label>
      <select><option>After 7 days</option><option>After 30 days</option><option>Never</option></select>
    </div>
    <div class="form-row">
      <label>WIP Limits</label>
      <select><option>Disabled</option><option>5 per column</option><option>3 per column</option></select>
    </div>
    <div class="form-row">
      <label>Default Assignee</label>
      <select><option>Unassigned</option><option>{members[0]}</option><option>{members[1]}</option><option>{members[2]}</option></select>
    </div>
    <div class="form-row" style="border-bottom:none;padding-bottom:0">
      <label></label>
      <button class="btn btn-primary">Save Board</button>
    </div>
  </div>
</section>
"""

    # ═════════════════════════════════════════════════════════════════
    #  4. Chat App
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def _layout_chat_app(
        primary: str,
        secondary: str,
        surface: str,
        text_color: str,
        text_muted: str,
        border: str,
        border_strong: str,
        input_bg: str,
        is_dark: bool,
        project_name: str,
    ) -> str:
        n = HtmlLayouts._int_from_name(project_name, "chat", 100)
        names = ["Alex", "Jordan", "Morgan", "Taylor", "Casey", "Riley", "Quinn", "Avery"]
        chats = [
            ("Product Team", "Sounds good, let's ship it!", True,  2),
            ("Design Review", "Can you update the mockups?", True,  0),
            ("Dev Ops Alert", "Deploy finished successfully " + chr(10004), False, 5),
            ("Sprint Planning", "Story points: 34 remaining", True,  1),
            ("Client: Acme Inc", "We need an ETA for phase 2", True,  3),
            ("General Chat", "Who's covering standup?", False,    0),
        ]

        # Build conversation list items to avoid deeply nested f-string expressions
        conv_items = HtmlLayouts._build_chat_conv_items(
            chats, primary, secondary, surface, border, text_color, text_muted,
        )
        bubble_items = HtmlLayouts._build_chat_bubbles(
            primary, secondary, input_bg, text_color, text_muted, n,
        )
        table_rows = HtmlLayouts._build_chat_table_rows(
            chats, primary, text_muted, n,
        )
        member_items = HtmlLayouts._build_chat_member_items(
            names, primary, secondary, input_bg, border, surface, n,
        )

        return f"""<section class="view active" data-view="main">
  <div class="header-row">
    <h1>💬 {project_name or 'Chat'}</h1>
    <span style="color:{text_muted};font-size:13px">{sum(c[3] for c in chats)} unread</span>
  </div>
  <div style="display:grid;grid-template-columns:300px 1fr;gap:0;background:{surface};border-radius:12px;border:1px solid {border};overflow:hidden;min-height:480px">
    <div style="border-right:1px solid {border};overflow-y:auto">
      <div style="padding:12px;border-bottom:1px solid {border}">
        <input type="text" placeholder="Search conversations..." style="width:100%;padding:8px 12px;border-radius:8px;border:1px solid {border_strong};background:{input_bg};color:{text_color};font-size:13px;font-family:inherit">
      </div>
{conv_items}
    </div>
    <div style="display:flex;flex-direction:column;height:480px">
      <div style="padding:14px 16px;border-bottom:1px solid {border};display:flex;align-items:center;gap:10px">
        <div class="avatar" style="width:32px;height:32px;font-size:13px;background:{primary}">P</div>
        <div><div style="font-size:14px;font-weight:600">Product Team</div><div style="font-size:11px;color:{secondary}">● Online</div></div>
      </div>
      <div style="flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px">
{bubble_items}
      </div>
      <div style="padding:12px 16px;border-top:1px solid {border};display:flex;gap:8px">
        <input type="text" placeholder="Type a message..." style="flex:1;padding:10px 14px;border-radius:8px;border:1px solid {border_strong};background:{input_bg};color:{text_color};font-size:14px;font-family:inherit">
        <button class="btn btn-primary" style="padding:10px 20px">Send</button>
      </div>
    </div>
  </div>
</section>

<section class="view" data-view="list">
  <div class="header-row">
    <h1>📋 All Conversations</h1>
  </div>
  <table class="list-table">
    <thead>
      <tr><th>Channel</th><th>Last Message</th><th>Unread</th><th>Members</th><th>Last Active</th></tr>
    </thead>
    <tbody>
{table_rows}
    </tbody>
  </table>
</section>

<section class="view" data-view="detail">
  <div class="header-row">
    <h1>🔍 Product Team Chat</h1>
    <button class="btn btn-outline">👤 View Members</button>
  </div>
  <div style="background:{surface};border-radius:12px;border:1px solid {border};padding:24px">
    <h3 style="margin-bottom:12px">Channel Details</h3>
    <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:20px">
      <div><span class="avatar" style="width:36px;height:36px;font-size:14px;background:{primary}">P</span></div>
      <div><div style="font-size:14px;font-weight:500">Product Team</div><div style="font-size:12px;color:{text_muted}">Created {n%12+1} months ago · {n%5+3} members</div></div>
    </div>
    <div class="form-row"><label>Channel Name</label><span>#product-team</span></div>
    <div class="form-row"><label>Topic</label><span style="color:{text_muted}">Product discussions, releases, and feedback</span></div>
    <div class="form-row"><label>Description</label><span style="color:{text_muted}">For the {project_name or 'product'} team to coordinate development</span></div>
    <div class="form-row"><label>Notification</label><select style="flex:0 0 160px"><option>All messages</option><option>Mentions only</option><option>Muted</option></select></div>
    <h4 style="margin:20px 0 10px">Members ({n%5+3})</h4>
    <div style="display:flex;gap:12px;flex-wrap:wrap">
{member_items}
    </div>
  </div>
</section>

<section class="view" data-view="settings">
  <div class="header-row"><h1>⚙️ Chat Settings</h1></div>
  <div style="background:{surface};border-radius:12px;border:1px solid {border};padding:24px">
    <div class="form-row">
      <label>Display Name</label>
      <input type="text" value="{project_name or 'User'}">
    </div>
    <div class="form-row">
      <label>Status</label>
      <select><option>Online</option><option>Away</option><option>Do Not Disturb</option><option>Invisible</option></select>
    </div>
    <div class="form-row">
      <label>Message Sound</label>
      <select><option>Enabled</option><option>Disabled</option></select>
    </div>
    <div class="form-row">
      <label>Show Typing Indicator</label>
      <select><option>Always</option><option>Contacts only</option><option>Disabled</option></select>
    </div>
    <div class="form-row">
      <label>Notification Preview</label>
      <select><option>Show name & message</option><option>Show name only</option><option>Hidden</option></select>
    </div>
    <div class="form-row" style="border-bottom:none;padding-bottom:0">
      <label></label>
      <button class="btn btn-primary">Save Settings</button>
    </div>
  </div>
</section>
"""

    # ═════════════════════════════════════════════════════════════════
    #  5. E-commerce
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def _layout_ecommerce(
        primary: str,
        secondary: str,
        surface: str,
        text_color: str,
        text_muted: str,
        border: str,
        border_strong: str,
        input_bg: str,
        is_dark: bool,
        project_name: str,
    ) -> str:
        n = HtmlLayouts._int_from_name(project_name, "ecom", 100)
        products = [
            ("Wireless Headphones Pro", f"${79 + n % 50}", f"{4 + n % 2}.{n%5}", 42 + n),
            ("Ergonomic Keyboard", f"${129 + n % 30}", f"{3 + n % 3}.{n%5}", 28 + n),
            ("Ultra-Light Laptop Stand", f"${49 + n % 20}", f"{4 + n % 2}.{n%5}", 65 + n),
            ("Smart Water Bottle", f"${34 + n % 15}", f"{3 + n % 3}.{n%5}", 91 + n),
            ("Noise-Canceling Earbuds", f"${149 + n % 40}", f"{4 + n % 2}.{n%5}", 55 + n),
            ("Minimalist Desk Lamp", f"${59 + n % 25}", f"{3 + n % 3}.{n%5}", 38 + n),
        ]

        categories = ["All", "Electronics", "Accessories", "Home Office", "Gadgets", "New Arrivals"]
        stars = "★"

        return f"""<section class="view active" data-view="main">
  <div class="header-row">
    <h1>🛍️ {project_name or 'Shop'}</h1>
    <div style="display:flex;gap:8px;align-items:center">
      <span style="font-size:13px;color:{text_muted}">{n % 6 + 1} items in cart</span>
      <button class="btn btn-primary">🛒 Cart ({n % 6 + 1})</button>
    </div>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap">
{''.join(f'    <span class="badge{" active" if i==0 else ""}" style="padding:6px 16px;cursor:pointer;font-size:13px;background:{primary if i==0 else input_bg};color:{"#fff" if i==0 else text_color};border:1px solid {border_strong if i!=0 else "transparent"}">{cat}</span>' for i, cat in enumerate(categories))}
  </div>
  <div class="card-grid" style="grid-template-columns:repeat(auto-fill,minmax(220px,1fr))">
{''.join(f'    <div class="card" style="padding:0;overflow:hidden">'
    f'<div style="height:160px;background:linear-gradient(135deg,{[primary,secondary,primary+"80"][idx%3]},{[secondary+"80",primary+"cc",secondary+"cc"][idx%3]});display:flex;align-items:center;justify-content:center;font-size:40px;color:rgba(255,255,255,0.6)">🖼️</div>'
    f'<div style="padding:16px">'
    f'<h3 style="font-size:14px;font-weight:600;margin-bottom:4px">{name}</h3>'
    f'<div style="font-size:12px;color:{text_muted};margin-bottom:8px">{len(name)*10} sold</div>'
    f'<div style="display:flex;justify-content:space-between;align-items:center">'
    f'<span style="font-size:18px;font-weight:700;color:{primary}">{price}</span>'
    f'<span style="font-size:13px;color:#f59e0b">{stars*int(rating[0])} {rating}</span>'
    f'</div>'
    f'<button class="btn btn-outline" style="width:100%;margin-top:12px;justify-content:center">Add to Cart</button>'
    f'</div>'
    f'</div>' for idx, (name, price, rating, sold) in enumerate(products))}
  </div>
</section>

<section class="view" data-view="list">
  <div class="header-row">
    <h1>📋 Product Inventory</h1>
    <input type="text" placeholder="Search products..." style="padding:8px 14px;border-radius:8px;border:1px solid {border_strong};background:{input_bg};color:{text_color};width:240px;font-size:14px;font-family:inherit">
  </div>
  <table class="list-table">
    <thead>
      <tr><th>Product</th><th>Price</th><th>Rating</th><th>Stock</th><th>Category</th><th>Status</th></tr>
    </thead>
    <tbody>
{''.join(f'      <tr><td style="font-weight:500">{p[0]}</td><td style="color:{primary};font-weight:600">{p[1]}</td><td style="color:#f59e0b">{p[2]}</td><td style="color:{text_muted}">{p[3]}</td><td style="color:{text_muted}">{["Electronics","Accessories","Office","Lifestyle","Audio","Lighting"][i%6]}</td><td><span class="badge{"-ok" if p[3]%2==0 else "-warn"}">{"In Stock" if p[3]%2==0 else "Low Stock"}</span></td></tr>' for i, p in enumerate(products))}
    </tbody>
  </table>
</section>

<section class="view" data-view="detail">
  <div class="header-row">
    <h1>🔍 {products[0][0]}</h1>
    <span class="badge badge-ok">In Stock</span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
    <div style="background:linear-gradient(135deg,{primary}30,{secondary}30);border-radius:12px;border:1px solid {border};height:280px;display:flex;align-items:center;justify-content:center;font-size:64px;color:rgba(255,255,255,0.4)">🖼️</div>
    <div style="background:{surface};border-radius:12px;border:1px solid {border};padding:24px">
      <h2 style="font-size:22px;font-weight:700;margin-bottom:8px">{products[0][0]}</h2>
      <div style="font-size:28px;font-weight:700;color:{primary};margin-bottom:12px">{products[0][1]}</div>
      <div style="color:#f59e0b;font-size:16px;margin-bottom:12px">{stars*int(products[0][2][0])} {products[0][2]}</div>
      <p style="color:{text_muted};font-size:14px;line-height:1.7;margin-bottom:16px">
        Premium {project_name or 'product'} designed for professionals who demand the best.
        Features include premium materials, ergonomic design, and {n+1}-year warranty.
        Perfect for home and office use.
      </p>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">
        <span class="badge" style="background:{primary}15;color:{primary}">Free Shipping</span>
        <span class="badge badge-ok">In Stock</span>
        <span class="badge badge-warn">Best Seller</span>
      </div>
      <button class="btn btn-primary" style="width:100%;justify-content:center;padding:12px">Add to Cart — {products[0][1]}</button>
    </div>
  </div>
  <h3 style="margin:20px 0 10px">Customer Reviews</h3>
  <div style="display:flex;flex-direction:column;gap:10px">
{"".join(f'    <div style="background:{surface};border-radius:10px;border:1px solid {border};padding:14px">'
    f'<div style="display:flex;justify-content:space-between;margin-bottom:6px">'
    f'<span style="font-weight:500;font-size:14px">{["Alex M.","Jordan K.","Taylor R.","Sam W.","Morgan P."][i%5]}</span>'
    f'<span style="color:#f59e0b;font-size:13px">{stars*(5-(i%3))} </span>'
    f'</div>'
    f'<p style="font-size:13px;color:{text_muted};line-height:1.5">{["Amazing product, exceeded my expectations!","Good quality for the price.","Solid build, would recommend.","Exactly what I needed. Fast delivery too.","Great but could use more color options."][i%5]}</p>'
    f'</div>' for i in range(5))}
  </div>
</section>

<section class="view" data-view="settings">
  <div class="header-row"><h1>⚙️ Store Settings</h1></div>
  <div style="background:{surface};border-radius:12px;border:1px solid {border};padding:24px">
    <div class="form-row">
      <label>Store Name</label>
      <input type="text" value="{project_name or 'My Store'}">
    </div>
    <div class="form-row">
      <label>Currency</label>
      <select><option>USD ($)</option><option>EUR (€)</option><option>CNY (¥)</option></select>
    </div>
    <div class="form-row">
      <label>Tax Rate (%)</label>
      <input type="number" value="{n % 15 + 5}">
    </div>
    <div class="form-row">
      <label>Shipping Policy</label>
      <select><option>Free shipping over $50</option><option>Free shipping over $100</option><option>Flat rate $5.99</option></select>
    </div>
    <div class="form-row">
      <label>Low Stock Threshold</label>
      <input type="number" value="{n % 20 + 5}">
    </div>
    <div class="form-row" style="border-bottom:none;padding-bottom:0">
      <label></label>
      <button class="btn btn-primary">Save Store Settings</button>
    </div>
  </div>
</section>
"""

    # ═════════════════════════════════════════════════════════════════
    #  6. Blog Layout
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def _layout_blog_layout(
        primary: str,
        secondary: str,
        surface: str,
        text_color: str,
        text_muted: str,
        border: str,
        border_strong: str,
        input_bg: str,
        is_dark: bool,
        project_name: str,
    ) -> str:
        n = HtmlLayouts._int_from_name(project_name, "blog", 100)

        articles = [
            ("Getting Started with {0}: A Complete Guide",
             "Learn everything you need to know about {0} in this comprehensive beginner's guide.",
             "Alex Chen", f"{n%12+1} min read", f"#{n}"),
            ("10 Advanced Techniques for {0} Power Users",
             "Take your {0} skills to the next level with these advanced tips and tricks from industry experts.",
             "Jordan Lee", f"{n%8+5} min read", f"#{n+1}"),
            ("Building Scalable Systems with {0} and Cloud Native Tools",
             "Architecture patterns for building production-ready applications with modern cloud infrastructure.",
             "Sam Rivera", f"{n%6+8} min read", f"#{n+2}"),
            ("The Future of {0}: Trends to Watch in 2026",
             "Industry predictions and emerging patterns that will shape how we build with {0} going forward.",
             "Morgan Wu", f"{n%5+6} min read", f"#{n+3}"),
            ("{0} Case Study: From Prototype to Production in 30 Days",
             "How Company X shipped their {0}-powered product in under a month with impressive results.",
             "Taylor Park", f"{n%4+10} min read", f"#{n+4}"),
        ]

        topics = [
            "Tutorials", "Case Studies", "Architecture",
            "Best Practices", "Release Notes", "Community",
        ]

        return f"""<section class="view active" data-view="main">
  <div class="header-row">
    <h1>📝 {project_name or 'Blog'}</h1>
    <button class="btn btn-primary">✏️ New Post</button>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap">
{''.join(f'    <span class="badge" style="padding:6px 16px;cursor:pointer;font-size:13px;background:{primary if i==0 else input_bg};color:{"#fff" if i==0 else text_color};border:1px solid {border_strong if i!=0 else "transparent"}">{topic}</span>' for i, topic in enumerate(topics))}
  </div>
  <!-- Featured article -->
  <div style="background:{surface};border-radius:12px;border:1px solid {border};overflow:hidden;margin-bottom:20px;display:grid;grid-template-columns:280px 1fr;cursor:pointer">
    <div style="height:200px;background:linear-gradient(135deg,{primary}40,{secondary}50);display:flex;align-items:center;justify-content:center;font-size:48px;color:rgba(255,255,255,0.5)">📰</div>
    <div style="padding:24px">
      <span class="badge" style="background:{primary}15;color:{primary};font-size:11px">Featured</span>
      <h2 style="font-size:20px;font-weight:700;margin:10px 0 8px">{articles[0][0].format(project_name or 'this framework')}</h2>
      <p style="color:{text_muted};font-size:14px;line-height:1.6;margin-bottom:14px">{articles[0][1].format(project_name or 'this framework')[:120]}...</p>
      <div style="display:flex;align-items:center;gap:12px;font-size:13px;color:{text_muted}">
        <span style="color:{primary};font-weight:500">{articles[0][2]}</span>
        <span>·</span>
        <span>{articles[0][3]}</span>
        <span>·</span>
        <span>{(n+1)*2} comments</span>
      </div>
    </div>
  </div>
  <!-- Article grid -->
  <h3 style="font-size:16px;font-weight:600;margin-bottom:14px">Latest Articles</h3>
  <div class="card-grid" style="grid-template-columns:repeat(auto-fill,minmax(280px,1fr))">
{"".join(f'    <div class="card" style="padding:0;overflow:hidden;cursor:pointer">'
    f'<div style="height:140px;background:linear-gradient(135deg,{[primary,secondary,primary+"80",secondary+"80",primary+"cc"][i%5]}30,{[primary,secondary,primary+"80",secondary+"80",primary+"cc"][(i+2)%5]}40);display:flex;align-items:center;justify-content:center;font-size:32px;color:rgba(255,255,255,0.4)">📄</div>'
    f'<div style="padding:16px">'
    f'<div style="display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap">'
    f'<span class="badge" style="background:{primary}15;color:{primary};font-size:10px">{["Tutorial","Deep Dive","News","Guide","Opinion"][i%5]}</span>'
    f'<span class="badge badge-warn" style="font-size:10px">{["New","Popular","Trending"][i%3]}</span>'
    f'</div>'
    f'<h3 style="font-size:15px;font-weight:600;margin-bottom:6px;line-height:1.4">{a[0].format(project_name or "Platform")[:70]}</h3>'
    f'<p style="font-size:13px;color:{text_muted};line-height:1.5;margin-bottom:10px">{a[1].format(project_name or "the platform")[:90]}...</p>'
    f'<div style="display:flex;justify-content:space-between;font-size:12px;color:{text_muted}"><span>{a[2]}</span><span>{a[3]}</span></div>'
    f'</div>'
    f'</div>' for i, a in enumerate(articles[1:]))}
  </div>
</section>

<section class="view" data-view="list">
  <div class="header-row">
    <h1>📋 All Posts</h1>
    <div>
      <button class="btn btn-outline" style="margin-right:8px">📁 Categories</button>
      <button class="btn btn-primary">✏️ New Post</button>
    </div>
  </div>
  <table class="list-table">
    <thead>
      <tr><th>Title</th><th>Author</th><th>Category</th><th>Status</th><th>Published</th><th>Views</th></tr>
    </thead>
    <tbody>
{''.join(f'      <tr><td style="font-weight:500;max-width:280px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{a[0].format(project_name or "Platform")[:60]}</td><td style="color:{text_muted}">{a[2]}</td><td style="color:{text_muted}">{["Tutorial","Architecture","Trends","Case Study","Guide"][i%5]}</td><td><span class="badge{"-ok" if i%3!=2 else ""}">{["Published","Published","Draft"][i%3]}</span></td><td style="color:{text_muted}">2026-{(i%12)+1:02d}-{(i%28)+1:02d}</td><td style="color:{text_muted}">{(n+1)*100+i*50}</td></tr>' for i, a in enumerate(articles))}
    </tbody>
  </table>
</section>

<section class="view" data-view="detail">
  <div class="header-row">
    <h1>🔍 {articles[0][0].format(project_name or 'Platform')}</h1>
    <span class="badge badge-ok">Published</span>
  </div>
  <div style="background:{surface};border-radius:12px;border:1px solid {border};padding:24px">
    <div style="display:flex;gap:16px;align-items:center;margin-bottom:20px;flex-wrap:wrap">
      <div style="display:flex;align-items:center;gap:8px"><span class="avatar" style="width:36px;height:36px;font-size:14px;background:{primary}">AC</span><span style="font-weight:500">{articles[0][2]}</span></div>
      <span style="color:{text_muted};font-size:13px">{articles[0][3]}</span>
      <span style="color:{text_muted};font-size:13px">· {(n+1)*2} comments</span>
      <span style="color:{primary};font-size:13px">● {n%20+80}% reader score</span>
    </div>
    <div style="height:200px;background:linear-gradient(135deg,{primary}20,{secondary}30);border-radius:10px;margin-bottom:20px;display:flex;align-items:center;justify-content:center;font-size:40px;color:rgba(255,255,255,0.4)">📰</div>
    <p style="color:{text_muted};font-size:15px;line-height:1.8">
      {project_name or 'This framework'} has rapidly become one of the most popular tools for modern
      development teams. In this guide, we'll walk through the fundamentals and get you productive
      in no time. We'll cover installation, configuration, core concepts, and real-world examples
      that demonstrate the power and flexibility of the platform.
    </p>
    <p style="color:{text_muted};font-size:15px;line-height:1.8;margin-top:16px">
      By the end of this article, you'll have a solid understanding of the architecture and be
      ready to build your first application. We've included code samples, configuration snippets,
      and best practices gathered from production deployments.
    </p>
  </div>
</section>

<section class="view" data-view="settings">
  <div class="header-row"><h1>⚙️ Blog Settings</h1></div>
  <div style="background:{surface};border-radius:12px;border:1px solid {border};padding:24px">
    <div class="form-row">
      <label>Blog Title</label>
      <input type="text" value="{project_name or 'Blog'}">
    </div>
    <div class="form-row">
      <label>Posts Per Page</label>
      <select><option>10</option><option>20</option><option>50</option></select>
    </div>
    <div class="form-row">
      <label>Comment Moderation</label>
      <select><option>Manual approval</option><option>Auto-approve registered users</option><option>Disabled</option></select>
    </div>
    <div class="form-row">
      <label>Enable RSS Feed</label>
      <select><option>Enabled</option><option>Disabled</option></select>
    </div>
    <div class="form-row">
      <label>Default Author</label>
      <input type="text" value="{articles[0][2]}">
    </div>
    <div class="form-row" style="border-bottom:none;padding-bottom:0">
      <label></label>
      <button class="btn btn-primary">Save Blog Settings</button>
    </div>
  </div>
</section>
"""

    # ═════════════════════════════════════════════════════════════════
    #  7. Settings Page
    # ═════════════════════════════════════════════════════════════════

    @staticmethod
    def _layout_settings_page(
        primary: str,
        secondary: str,
        surface: str,
        text_color: str,
        text_muted: str,
        border: str,
        border_strong: str,
        input_bg: str,
        is_dark: bool,
        project_name: str,
    ) -> str:
        n = HtmlLayouts._int_from_name(project_name, "settings", 100)
        tabs = ["General", "Security", "Notifications", "Appearance", "Billing", "Integrations"]

        return f"""<section class="view active" data-view="main">
  <div class="header-row">
    <h1>⚙️ {project_name or 'Settings'}</h1>
    <span style="font-size:13px;color:{text_muted}">Last saved: {n%24}:{(n*3)%60:02d}</span>
  </div>
  <div style="display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap">
{''.join(f'    <span class="badge" style="padding:8px 18px;cursor:pointer;font-size:13px;background:{primary if i==0 else input_bg};color:{"#fff" if i==0 else text_color};border:1px solid {border_strong if i!=0 else "transparent"};border-radius:8px">{tab}</span>' for i, tab in enumerate(tabs))}
  </div>
  <div style="background:{surface};border-radius:12px;border:1px solid {border};overflow:hidden">
    <h3 style="padding:20px 24px 12px;font-size:16px;font-weight:600;border-bottom:1px solid {border}">General Settings</h3>
    <div style="padding:4px 24px 20px">
      <div class="form-row">
        <label>Project Name</label>
        <input type="text" value="{project_name or 'My Project'}">
      </div>
      <div class="form-row">
        <label>Default Language</label>
        <select><option>English</option><option>Chinese (中文)</option><option>Japanese (日本語)</option><option>Korean (한국어)</option></select>
      </div>
      <div class="form-row">
        <label>Time Zone</label>
        <select><option>UTC+8 (Asia/Shanghai)</option><option>UTC+0 (UTC)</option><option>UTC-5 (Eastern US)</option><option>UTC-8 (Pacific US)</option></select>
      </div>
      <div class="form-row">
        <label>Date Format</label>
        <select><option>YYYY-MM-DD</option><option>MM/DD/YYYY</option><option>DD/MM/YYYY</option></select>
      </div>
    </div>

    <h3 style="padding:12px 24px 12px;font-size:16px;font-weight:600;border-top:1px solid {border};border-bottom:1px solid {border};background:{input_bg}">Security</h3>
    <div style="padding:4px 24px 20px">
      <div class="form-row">
        <label>Two-Factor Auth</label>
        <select><option>Enabled</option><option>Disabled</option></select>
      </div>
      <div class="form-row">
        <label>Session Timeout</label>
        <select><option>30 minutes</option><option>1 hour</option><option>4 hours</option><option>24 hours</option></select>
      </div>
      <div class="form-row">
        <label>Password Min. Length</label>
        <input type="number" value="{n%4+8}">
      </div>
      <div class="form-row" style="border-bottom:none">
        <label>API Key</label>
        <div style="display:flex;gap:8px;align-items:center;flex:1">
          <code style="padding:6px 12px;background:{input_bg};border-radius:6px;border:1px solid {border_strong};font-size:13px;color:{text_muted}">sk-{hashlib.md5(project_name.encode()).hexdigest()[:16]}</code>
          <button class="btn btn-outline" style="padding:6px 14px;font-size:12px">Regenerate</button>
        </div>
      </div>
    </div>

    <h3 style="padding:12px 24px 12px;font-size:16px;font-weight:600;border-top:1px solid {border};border-bottom:1px solid {border};background:{input_bg}">Notifications</h3>
    <div style="padding:4px 24px 20px">
{"".join(f'      <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid {border}">'
        f'<div><div style="font-size:14px">{notif}</div><div style="font-size:12px;color:{text_muted}">{desc}</div></div>'
        f'<label style="position:relative;display:inline-block;width:44px;height:24px"><input type="checkbox" {"checked" if (n+idx)%2==0 else ""} style="opacity:0;width:0;height:0">'
        f'<span style="position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:{primary if (n+idx)%2==0 else border_strong};border-radius:24px;transition:0.3s"></span>'
        f'<span style="position:absolute;content:"";height:18px;width:18px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:0.3s;{"transform:translateX(20px)" if (n+idx)%2==0 else ""}"></span>'
        f'</label></div>' for idx, (notif, desc) in enumerate([
        ("Email Notifications", "Receive updates via email"),
        ("Push Notifications", "Browser push alerts"),
        ("Slack Integration", "Send updates to Slack channel"),
        ("Weekly Digest", "Weekly summary of activity"),
        ("SMS Alerts", "Critical alerts via SMS"),
    ]))}
    </div>

    <h3 style="padding:12px 24px 12px;font-size:16px;font-weight:600;border-top:1px solid {border};border-bottom:1px solid {border};background:{input_bg}">Appearance</h3>
    <div style="padding:4px 24px 20px">
      <div class="form-row">
        <label>Theme</label>
        <select><option>{"Dark" if is_dark else "Light"}</option><option>{"Light" if is_dark else "Dark"}</option><option>System</option></select>
      </div>
      <div class="form-row">
        <label>Primary Color</label>
        <div style="display:flex;gap:8px;align-items:center;flex:1">
          <span style="display:inline-block;width:28px;height:28px;border-radius:6px;background:{primary};border:2px solid {border_strong}"></span>
          <code style="font-size:13px;color:{text_muted}">{primary}</code>
        </div>
      </div>
      <div class="form-row">
        <label>Font Size</label>
        <select><option>Small</option><option selected>Medium</option><option>Large</option></select>
      </div>
      <div class="form-row" style="border-bottom:none">
        <label>Compact Mode</label>
        <select><option>Disabled</option><option>Enabled</option></select>
      </div>
    </div>
  </div>
  <div style="margin-top:20px;display:flex;gap:12px;justify-content:flex-end">
    <button class="btn btn-outline">Discard Changes</button>
    <button class="btn btn-primary">Save All Settings</button>
  </div>
</section>

<section class="view" data-view="list">
  <div class="header-row">
    <h1>📋 Configuration Audit Log</h1>
  </div>
  <table class="list-table">
    <thead>
      <tr><th>Action</th><th>User</th><th>Field</th><th>Old Value</th><th>New Value</th><th>Timestamp</th></tr>
    </thead>
    <tbody>
{''.join(f'      <tr><td style="font-weight:500">{action}</td><td style="color:{text_muted}">{user}</td><td style="color:{text_muted}">{field}</td><td style="color:{text_muted};max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{old}</td><td style="color:{text_muted};max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{new_}</td><td style="color:{text_muted}">{time}</td></tr>' for action, user, field, old, new_, time in [
    ("Updated", "admin@co.com", "theme", "light", "dark", "2026-06-07 14:32"),
    ("Updated", "admin@co.com", "language", "en", "zh-CN", "2026-06-06 09:15"),
    ("Updated", "user@co.com", "timezone", "UTC", "Asia/Shanghai", "2026-06-05 16:44"),
    ("Regenerated", "admin@co.com", "api_key", "sk-old***", "sk-new***", "2026-06-04 11:20"),
    ("Updated", "admin@co.com", "2fa", "disabled", "enabled", "2026-06-03 08:55"),
])}
    </tbody>
  </table>
</section>

<section class="view" data-view="detail">
  <div class="header-row">
    <h1>🔍 API Key Management</h1>
    <button class="btn btn-outline">📋 Copy Key</button>
  </div>
  <div style="background:{surface};border-radius:12px;border:1px solid {border};padding:24px">
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:20px">
      <div class="stat-card" style="flex:1;min-width:140px">
        <div class="label">Active Keys</div>
        <div class="value" style="font-size:22px;color:{primary}">{n%5+2}</div>
      </div>
      <div class="stat-card" style="flex:1;min-width:140px">
        <div class="label">Requests Today</div>
        <div class="value" style="font-size:22px;color:{secondary}">{n*134+500}</div>
      </div>
      <div class="stat-card" style="flex:1;min-width:140px">
        <div class="label">Rate Limit</div>
        <div class="value" style="font-size:22px;color:{primary}">{(n%5+1)*1000}/hr</div>
      </div>
    </div>
    <h4 style="margin-bottom:10px">Your API Keys</h4>
{"".join(f'    <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-radius:8px;border:1px solid {border};margin-bottom:8px;background:{input_bg}">'
    f'<div><code style="font-size:13px;color:{text_color}">sk-{hashlib.md5((project_name+str(i)).encode()).hexdigest()[:12]}...</code><div style="font-size:12px;color:{text_muted};margin-top:2px">Created 2026-0{(i%9)+1}-{(i%28)+1:02d} · {"Read & Write" if i%2==0 else "Read Only"}</div></div>'
    f'<div style="display:flex;gap:8px">'
    f'<span class="badge{"-ok" if i>0 else ""}" style="font-size:11px">{"Active" if i>0 else "Expired"}</span>'
    f'<button class="btn btn-outline" style="padding:4px 12px;font-size:12px">Revoke</button>'
    f'</div></div>' for i in range(n%3+2))}
    <button class="btn btn-primary" style="margin-top:8px">+ Generate New Key</button>
  </div>
</section>

<section class="view" data-view="settings">
  <div class="header-row"><h1>⚙️ Advanced Settings</h1></div>
  <div style="background:{surface};border-radius:12px;border:1px solid {border};padding:24px">
    <div class="form-row">
      <label>Developer Mode</label>
      <select><option>Disabled</option><option>Enabled</option></select>
      <div class="hint">Enables debugging tools and verbose logging</div>
    </div>
    <div class="form-row">
      <label>Log Level</label>
      <select><option>Info</option><option>Debug</option><option>Warning</option><option>Error</option></select>
    </div>
    <div class="form-row">
      <label>Data Retention (days)</label>
      <input type="number" value="{n*3+30}">
      <div class="hint">Auto-delete logs older than this period</div>
    </div>
    <div class="form-row">
      <label>Export Format</label>
      <select><option>JSON</option><option>CSV</option><option>YAML</option></select>
    </div>
    <div class="form-row">
      <label>Maintenance Mode</label>
      <select><option>Disabled</option><option>Enabled</option></select>
      <div class="hint" style="color:#ef4444">Blocks all non-admin access</div>
    </div>
    <div class="form-row" style="border-bottom:none;padding-bottom:0">
      <label></label>
      <button class="btn btn-primary">Apply Advanced Settings</button>
    </div>
  </div>
  <div style="margin-top:16px;background:{surface};border-radius:12px;border:1px solid {border};padding:24px;text-align:center">
    <p style="color:{text_muted};font-size:14px;margin-bottom:8px">Danger Zone</p>
    <p style="color:{text_muted};font-size:13px;margin-bottom:16px">Once you delete this project, there is no going back. Please be certain.</p>
    <button style="padding:10px 28px;border-radius:8px;background:#ef4444;color:#fff;border:none;font-size:14px;font-weight:500;cursor:pointer;font-family:inherit">🗑️ Delete Project</button>
  </div>
</section>
"""
