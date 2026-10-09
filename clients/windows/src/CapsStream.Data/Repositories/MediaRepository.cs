using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using CapsStream.Core.Models;
using Dapper;

namespace CapsStream.Data.Repositories;

public class MediaRepository
{
    private readonly CapsDb _db;

    public MediaRepository(CapsDb db)
    {
        _db = db;
    }

    public async Task<MediaItem?> GetFeaturedHeroAsync()
    {
        using var conn = _db.CreateConnection();
        // Pick a top rated item that has a rich backdrop image
        var sql = @"SELECT * FROM media 
                    WHERE backdrop_path IS NOT NULL 
                      AND backdrop_path != '' 
                      AND overview IS NOT NULL 
                      AND overview != ''
                    ORDER BY rating DESC, vote_count DESC, added_at DESC 
                    LIMIT 1";
        var item = await conn.QueryFirstOrDefaultAsync<MediaItem>(sql);
        if (item == null)
        {
            // Fallback: any item with backdrop
            item = await conn.QueryFirstOrDefaultAsync<MediaItem>(
                "SELECT * FROM media WHERE backdrop_path IS NOT NULL AND backdrop_path != '' LIMIT 1"
            );
        }
        return item;
    }

    public async Task<IEnumerable<MediaItem>> GetAllAsync(string? type = null)
    {
        using var conn = _db.CreateConnection();
        string sql;
        if (string.IsNullOrEmpty(type) || type == MediaType.Movie)
        {
            sql = string.IsNullOrEmpty(type)
                ? "SELECT * FROM media ORDER BY title COLLATE NOCASE ASC"
                : "SELECT * FROM media WHERE type = @type ORDER BY title COLLATE NOCASE ASC";
        }
        else
        {
            sql = @"SELECT m.* FROM media m
                    JOIN (
                        SELECT
                            COALESCE(CAST(tmdb_id AS TEXT), title) AS grp,
                            MIN(CASE WHEN poster_path IS NOT NULL AND poster_path != '' THEN 0 ELSE 1 END) AS has_poster_rank,
                            MIN(CASE WHEN poster_path IS NOT NULL AND poster_path != '' THEN id ELSE NULL END) AS poster_id,
                            MIN(id) AS fallback_id
                        FROM media
                        WHERE type = @type
                        GROUP BY grp
                    ) best ON m.id = COALESCE(best.poster_id, best.fallback_id)
                    ORDER BY m.title COLLATE NOCASE ASC";
        }
        return await conn.QueryAsync<MediaItem>(sql, new { type });
    }

    public async Task<MediaItem?> GetByIdAsync(long id)
    {
        using var conn = _db.CreateConnection();
        return await conn.QueryFirstOrDefaultAsync<MediaItem>(
            "SELECT * FROM media WHERE id = @id", new { id }
        );
    }

    public async Task<IEnumerable<MediaItem>> GetRecentlyAddedAsync(int limit = 20)
    {
        using var conn = _db.CreateConnection();
        var sql = @"SELECT m.* FROM media m
                    JOIN (
                        SELECT
                            COALESCE(CAST(tmdb_id AS TEXT), title) AS grp,
                            MAX(id) AS max_id
                        FROM media
                        GROUP BY grp
                    ) best ON m.id = best.max_id
                    ORDER BY m.added_at DESC, m.id DESC
                    LIMIT @limit";
        return await conn.QueryAsync<MediaItem>(sql, new { limit });
    }

    public async Task<IEnumerable<MediaItem>> GetTopRatedAsync(string? type = null, int limit = 20)
    {
        using var conn = _db.CreateConnection();
        string typeClause = string.IsNullOrEmpty(type) ? "" : "AND type = @type";
        var sql = $@"SELECT m.* FROM media m
                     JOIN (
                         SELECT
                             COALESCE(CAST(tmdb_id AS TEXT), title) AS grp,
                             MAX(id) AS max_id
                         FROM media
                         WHERE 1=1 {typeClause}
                         GROUP BY grp
                     ) best ON m.id = best.max_id
                     WHERE m.rating > 0
                     ORDER BY m.rating DESC, m.vote_count DESC
                     LIMIT @limit";
        return await conn.QueryAsync<MediaItem>(sql, new { type, limit });
    }

    public async Task<IEnumerable<MediaItem>> SearchAsync(string query, string? type = null, int limit = 50)
    {
        using var conn = _db.CreateConnection();
        var sql = @"SELECT * FROM media 
                    WHERE (title LIKE @search OR original_title LIKE @search OR ep_title LIKE @search)";
        if (!string.IsNullOrEmpty(type))
        {
            sql += " AND type = @type";
        }
        sql += " ORDER BY rating DESC, title ASC LIMIT @limit";
        return await conn.QueryAsync<MediaItem>(sql, new { search = $"%{query}%", type, limit });
    }

    public async Task<IEnumerable<MediaItem>> GetContinueWatchingAsync(long profileId, int limit = 20)
    {
        using var conn = _db.CreateConnection();
        var sql = @"SELECT m.* FROM media m
                    INNER JOIN watch_progress wp ON m.id = wp.media_id
                    WHERE wp.profile_id = @profileId 
                      AND wp.completed = 0 
                      AND wp.position > 15
                    ORDER BY wp.updated_at DESC
                    LIMIT @limit";
        return await conn.QueryAsync<MediaItem>(sql, new { profileId, limit });
    }
}
