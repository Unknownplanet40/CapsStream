using System;

namespace CapsStream.Core.Models;

public class WatchProgress
{
    public long Id { get; set; }
    public long ProfileId { get; set; }
    public long MediaId { get; set; }
    public int Position { get; set; }
    public int Duration { get; set; }
    public bool Completed { get; set; }
    public DateTime? UpdatedAt { get; set; }

    public double Percent => Duration > 0 ? Math.Clamp((double)Position / Duration * 100.0, 0, 100) : 0;
}
