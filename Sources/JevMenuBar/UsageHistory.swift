import SQLite3
import SwiftUI

/// Decision requests recorded by the gateway's analytics store, bucketed over a window.
struct UsageSnapshot: Sendable, Equatable {
    /// Request counts per bucket, oldest slot first.
    let buckets: [Int]
    /// Cache-hit counts per bucket (a subset of `buckets`): answers served by the
    /// gateway's replay cache instead of a live model call.
    let cachedBuckets: [Int]
    let total: Int
    let cached: Int
    let latestActivity: Date?
    /// Right edge of the window at snapshot time; hour markers align against it.
    let windowEnd: Date
}

/// Reads request timestamps straight from the analytics database the gateway already
/// maintains (one `requests` row per incoming `/v1/decision` call, including replay
/// cache hits). Opening read-only never contends with the recorder's writer lock or
/// changes its contents.
enum UsageHistory {
    static let window: TimeInterval = 12 * 3600
    static let bucketCount = 72
    static let bucketSeconds = window / TimeInterval(bucketCount)

    static var databaseURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/JEV Menu Bar/analytics/requests.sqlite3")
    }

    /// Synchronous, blocking read; run from a background task.
    static func snapshot(now: Date = Date()) -> UsageSnapshot? {
        var database: OpaquePointer?
        guard sqlite3_open_v2(databaseURL.path, &database, SQLITE_OPEN_READONLY, nil) == SQLITE_OK,
              database != nil else {
            sqlite3_close_v2(database)
            return nil
        }
        defer { sqlite3_close_v2(database) }
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(database, "SELECT started_at, outcome FROM requests WHERE started_at >= ?", -1, &statement, nil) == SQLITE_OK,
              statement != nil else {
            return nil
        }
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_double(statement, 1, now.addingTimeInterval(-window).timeIntervalSince1970)
        var buckets = [Int](repeating: 0, count: bucketCount)
        var cachedBuckets = [Int](repeating: 0, count: bucketCount)
        var total = 0
        var cached = 0
        var latestActivity: Date?
        let windowStart = now.addingTimeInterval(-window)
        while sqlite3_step(statement) == SQLITE_ROW {
            let started = Date(timeIntervalSince1970: sqlite3_column_double(statement, 0))
            let slot = Int(started.timeIntervalSince(windowStart) / bucketSeconds)
            let clamped = min(max(slot, 0), bucketCount - 1)
            buckets[clamped] += 1
            total += 1
            if let column = sqlite3_column_text(statement, 1),
               String(cString: column) == "cache_hit" {
                cachedBuckets[clamped] += 1
                cached += 1
            }
            latestActivity = started
        }
        return UsageSnapshot(buckets: buckets, cachedBuckets: cachedBuckets, total: total,
                             cached: cached, latestActivity: latestActivity, windowEnd: now)
    }
}

/// Pulse strip that replaces the divider under the health-check line: the divider's
/// line becomes the baseline, and every 10-minute bucket with requests draws a bar —
/// blue for live model calls with the cache-hit share stacked on top in green — so
/// quiet stretches read as a flatline and bursts read as blips.
struct UsagePulseView: View {
    let snapshot: UsageSnapshot?

    private let stripHeight: CGFloat = 34
    private let axisHeight: CGFloat = 14

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Canvas { context, size in
                let baselineY = size.height - axisHeight - 0.5
                var baseline = Path()
                baseline.move(to: CGPoint(x: 0, y: baselineY))
                baseline.addLine(to: CGPoint(x: size.width, y: baselineY))
                context.stroke(baseline, with: .color(Color(nsColor: .separatorColor)), lineWidth: 1)
                drawHourAxis(in: context, width: size.width, baselineY: baselineY)
                guard let snapshot else { return }
                let peak = zip(snapshot.buckets, snapshot.cachedBuckets).map { $0 + $1 }.max() ?? 0
                guard peak > 0 else { return }
                let slotWidth = size.width / CGFloat(snapshot.buckets.count)
                let barWidth = max(1, slotWidth - 1)
                let maxHeight = baselineY - 2
                for (index, value) in snapshot.buckets.enumerated() where value > 0 {
                    let cached = snapshot.cachedBuckets[index]
                    let liveHeight = max(2, maxHeight * CGFloat(value) / CGFloat(peak))
                    let x = CGFloat(index) * slotWidth
                    let liveRect = CGRect(x: x, y: baselineY - liveHeight, width: barWidth, height: liveHeight)
                    context.fill(Path(liveRect), with: .color(Color.accentColor.opacity(value + cached == peak ? 0.95 : 0.7)))
                    if cached > 0 {
                        // Cached answers stack on top of the live bar in green, on the same scale.
                        let cachedHeight = max(2, maxHeight * CGFloat(cached) / CGFloat(peak))
                        let cachedRect = CGRect(x: x, y: liveRect.minY - cachedHeight, width: barWidth, height: cachedHeight)
                        context.fill(Path(cachedRect), with: .color(.green.opacity(value + cached == peak ? 0.95 : 0.75)))
                    }
                }
            }
            .frame(height: stripHeight + axisHeight)
            HStack {
                Text("Last 12 hours").font(.caption2).foregroundStyle(.secondary)
                Spacer()
                Text(caption).font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityText)
    }

    /// Hour ruler under the baseline: a small tick at every whole clock hour in the
    /// window, plus a zero-padded 24-hour label (00, 04, 08, …) at every fourth hour.
    private func drawHourAxis(in context: GraphicsContext, width: CGFloat, baselineY: CGFloat) {
        guard let snapshot else { return }
        let calendar = Calendar.current
        let windowStart = snapshot.windowEnd.addingTimeInterval(-UsageHistory.window)
        guard var hour = calendar.nextDate(after: windowStart, matching: DateComponents(minute: 0, second: 0),
                                           matchingPolicy: .nextTime) else { return }
        let tickColor = Color(nsColor: .separatorColor)
        while hour <= snapshot.windowEnd {
            let fraction = hour.timeIntervalSince(windowStart) / UsageHistory.window
            let x = min(max(CGFloat(fraction) * width, 0.5), width - 0.5)
            var tick = Path()
            tick.move(to: CGPoint(x: x, y: baselineY + 1))
            tick.addLine(to: CGPoint(x: x, y: baselineY + 4))
            context.stroke(tick, with: .color(tickColor), lineWidth: 1)
            let value = calendar.component(.hour, from: hour)
            if value % 4 == 0 {
                let label = Text(String(format: "%02d", value))
                    .font(.system(size: 9).monospacedDigit())
                    .foregroundColor(.secondary)
                context.draw(label, at: CGPoint(x: min(max(x, 7), width - 7), y: baselineY + axisHeight / 2))
            }
            guard let next = calendar.date(byAdding: .hour, value: 1, to: hour) else { break }
            hour = next
        }
    }

    private var caption: String {
        guard let snapshot else { return "usage history unavailable" }
        let live = snapshot.total - snapshot.cached
        return "Request: \(live)  ·  Cache: \(snapshot.cached)"
    }

    private var accessibilityText: String {
        guard let snapshot else { return "Usage history unavailable" }
        return "Usage in the last 12 hours: \(snapshot.total) requests, \(snapshot.cached) served from cache"
    }
}
