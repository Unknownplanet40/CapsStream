using System;
using System.IO;

namespace CapsStream.Core.Models;

public class MediaItem
{
    public static string? DataDirectory { get; set; }

    public long Id { get; set; }
    public string Type { get; set; } = MediaType.Movie;
    public long? TmdbId { get; set; }
    public string Title { get; set; } = string.Empty;
    public string? OriginalTitle { get; set; }
    public int? Year { get; set; }
    public int? Season { get; set; }
    public int? Episode { get; set; }
    public string? EpTitle { get; set; }
    public string FilePath { get; set; } = string.Empty;
    public long FileSize { get; set; }
    public int? Duration { get; set; }
    public string? AddedAt { get; set; }
    public string? Genres { get; set; }
    public double Rating { get; set; }
    public int VoteCount { get; set; }
    public string? Overview { get; set; }
    public string? Tagline { get; set; }
    public string? PosterPath { get; set; }
    public string? BackdropPath { get; set; }
    public string? LogoPath { get; set; }
    public string? TrailerKey { get; set; }
    public string? CastJson { get; set; }
    public bool TmdbMatched { get; set; }
    public bool ManuallyOverridden { get; set; }

    // Display Helpers
    public string DisplayTitle => Type == MediaType.Movie
        ? Title
        : (Season.HasValue && Episode.HasValue ? $"{Title} S{Season:D2}E{Episode:D2}{(string.IsNullOrEmpty(EpTitle) ? "" : $" - {EpTitle}")}" : Title);

    public string DisplayYear => Year.HasValue ? $"{Year.Value}" : string.Empty;

    public string FormattedRating => Rating > 0 ? $"★ {Rating:F1}" : string.Empty;

    public string QualityBadge
    {
        get
        {
            if (FilePath.Contains("2160p", StringComparison.OrdinalIgnoreCase) || FilePath.Contains("4K", StringComparison.OrdinalIgnoreCase))
                return "4K UHD";
            if (FilePath.Contains("1080p", StringComparison.OrdinalIgnoreCase))
                return "1080p";
            if (FilePath.Contains("720p", StringComparison.OrdinalIgnoreCase))
                return "720p";
            return "HD";
        }
    }

    public string FormattedDuration
    {
        get
        {
            if (!Duration.HasValue || Duration.Value <= 0) return string.Empty;
            var ts = TimeSpan.FromSeconds(Duration.Value);
            return ts.Hours > 0 ? $"{ts.Hours}h {ts.Minutes}m" : $"{ts.Minutes}m";
        }
    }

    public string PosterDisplayUri
    {
        get
        {
            if (string.IsNullOrWhiteSpace(PosterPath))
                return "ms-appx:///Assets/Square150x150Logo.scale-200.png";

            if (PosterPath.StartsWith("http://", StringComparison.OrdinalIgnoreCase) || 
                PosterPath.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
                return PosterPath;

            var baseDir = DataDirectory;
            if (!string.IsNullOrEmpty(baseDir))
            {
                var relPath = PosterPath.TrimStart('/', '\\').Replace('/', Path.DirectorySeparatorChar);

                var candidate1 = Path.Combine(baseDir, "metadata", relPath);
                if (File.Exists(candidate1))
                    return new Uri(candidate1).AbsoluteUri;

                var fileName = Path.GetFileName(PosterPath);
                var candidate2 = Path.Combine(baseDir, "metadata", "images", fileName);
                if (File.Exists(candidate2))
                    return new Uri(candidate2).AbsoluteUri;

                var candidate3 = Path.Combine(baseDir, relPath);
                if (File.Exists(candidate3))
                    return new Uri(candidate3).AbsoluteUri;
            }

            if (File.Exists(PosterPath))
                return new Uri(PosterPath).AbsoluteUri;

            return "ms-appx:///Assets/Square150x150Logo.scale-200.png";
        }
    }

    public string BackdropDisplayUri
    {
        get
        {
            if (string.IsNullOrWhiteSpace(BackdropPath))
                return PosterDisplayUri;

            if (BackdropPath.StartsWith("http://", StringComparison.OrdinalIgnoreCase) || 
                BackdropPath.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
                return BackdropPath;

            var baseDir = DataDirectory;
            if (!string.IsNullOrEmpty(baseDir))
            {
                var relPath = BackdropPath.TrimStart('/', '\\').Replace('/', Path.DirectorySeparatorChar);

                var candidate1 = Path.Combine(baseDir, "metadata", relPath);
                if (File.Exists(candidate1))
                    return new Uri(candidate1).AbsoluteUri;

                var fileName = Path.GetFileName(BackdropPath);
                var candidate2 = Path.Combine(baseDir, "metadata", "images", fileName);
                if (File.Exists(candidate2))
                    return new Uri(candidate2).AbsoluteUri;

                var candidate3 = Path.Combine(baseDir, relPath);
                if (File.Exists(candidate3))
                    return new Uri(candidate3).AbsoluteUri;
            }

            if (File.Exists(BackdropPath))
                return new Uri(BackdropPath).AbsoluteUri;

            return PosterDisplayUri;
        }
    }

    public string? LogoDisplayUri
    {
        get
        {
            if (string.IsNullOrWhiteSpace(LogoPath))
                return null;

            if (LogoPath.StartsWith("http://", StringComparison.OrdinalIgnoreCase) || 
                LogoPath.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
                return LogoPath;

            var baseDir = DataDirectory;
            if (!string.IsNullOrEmpty(baseDir))
            {
                var relPath = LogoPath.TrimStart('/', '\\').Replace('/', Path.DirectorySeparatorChar);

                var candidate1 = Path.Combine(baseDir, "metadata", relPath);
                if (File.Exists(candidate1))
                    return new Uri(candidate1).AbsoluteUri;

                var fileName = Path.GetFileName(LogoPath);
                var candidate2 = Path.Combine(baseDir, "metadata", "images", fileName);
                if (File.Exists(candidate2))
                    return new Uri(candidate2).AbsoluteUri;
            }

            if (File.Exists(LogoPath))
                return new Uri(LogoPath).AbsoluteUri;

            return null;
        }
    }

    public bool HasLogo => !string.IsNullOrEmpty(LogoDisplayUri);
}
