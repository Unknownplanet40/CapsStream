using System;

namespace CapsStream.Core.Models;

public class Profile
{
    public long Id { get; set; }
    public string Name { get; set; } = string.Empty;
    public string? PinHash { get; set; }
    public string Avatar { get; set; } = "ph-film-strip";
    public string Color { get; set; } = "#e50914";
    public DateTime? CreatedAt { get; set; }
}
