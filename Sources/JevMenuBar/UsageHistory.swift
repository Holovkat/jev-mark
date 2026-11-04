import SQLite3
import SwiftUI

/// Decision requests recorded by the gateway's analytics store, bucketed over a window.
struct UsageSnapshot: Sendable, Equatable {
    /// Request counts per bucket, oldest slot first.
    let buckets: [Int]
    let total: Int
    let latestActivity: Date?
    /// Right edge of the window at snapshot time; hour markers align against it.
    let windowEnd: Date
}

/// Reads request timestamps straight from the analytics database the gateway already
/// maintains (one `requests` row per incoming `/v1/decision` call). Opening read-only
/// never contends with the recorder's writer lock or changes its contents.
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
        guard sqlite3_prepare_v2(database, "SELECT started_at FROM requests WHERE started_at >= ?", -1, &statement, nil) == SQLITE_OK,
              statement != nil else {
            return nil
        }
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_double(statement, 1, now.addingTimeInterval(-window).timeIntervalSince1970)
        var buckets = [Int](repeating: 0, count: bucketCount)
        var total = 0
        var latestActivity: Date?
        let windowStart = now.addingTimeInterval(-window)
        while sqlite3_step(statement) == SQLITE_ROW {
            let started = Date(timeIntervalSince1970: sqlite3_column_double(statement, 0))
            let slot = Int(started.timeIntervalSince(windowStart) / bucketSeconds)
            buckets[min(max(slot, 0), bucketCount - 1)] += 1
            total += 1
            latestActivity = started
        }
        return UsageSnapshot(buckets: buckets, total: total, latestActivity: latestActivity, windowEnd: now)
    }
}

/// Pulse strip that replaces the divider under the health-check line: the divider's
/// line becomes the baseline, and every 10-minute bucket with requests draws a bar,
/// so quiet stretches read as a flatline and bursts read as blips.
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
                guard let snapshot, let peak = snapshot.buckets.max(), peak > 0 else { return }
                let slotWidth = size.width / CGFloat(snapshot.buckets.count)
                let barWidth = max(1, slotWidth - 1)
                let maxHeight = baselineY - 2
                for (index, value) in snapshot.buckets.enumerated() where value > 0 {
                    let height = max(2, maxHeight * CGFloat(value) / CGFloat(peak))
                    let rect = CGRect(x: CGFloat(index) * slotWidth, y: baselineY - height,
                                      width: barWidth, height: height)
                    context.fill(Path(rect), with: .color(Color.accentColor.opacity(value == peak ? 0.95 : 0.7)))
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
        return snapshot.total == 1 ? "1 request" : "\(snapshot.total) requests"
    }

    private var accessibilityText: String {
        guard let snapshot else { return "Usage history unavailable" }
        return "Usage in the last 12 hours: \(snapshot.total) requests"
    }
}
