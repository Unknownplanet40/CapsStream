using System;

namespace CapsStream.Core.Models;

public class WatchHistoryItem
{
    public long Id { get; set; }
    public long ProfileId { get; set; }
    public long? TmdbId { get; set; }
    public string Title { get; set; } = string.Empty;
    public string Type { get; set; } = MediaType.Movie;
    public int? Season { get; set; }
    public int? Episode { get; set; }
    public string? EpTitle { get; set; }
    public string? Genres { get; set; }
    public int? Year { get; set; }
    public string? PosterPath { get; set; }
    public int Position { get; set; }
    public int Duration { get; set; }
    public bool Completed { get; set; }
    public DateTime? UpdatedAt { get; set; }
}
