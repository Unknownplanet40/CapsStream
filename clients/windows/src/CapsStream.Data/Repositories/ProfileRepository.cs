using System.Collections.Generic;
using System.Threading.Tasks;
using CapsStream.Core.Models;
using Dapper;

namespace CapsStream.Data.Repositories;

public class ProfileRepository
{
    private readonly CapsDb _db;

    public ProfileRepository(CapsDb db)
    {
        _db = db;
    }

    public async Task<IEnumerable<Profile>> GetAllAsync()
    {
        using var conn = _db.CreateConnection();
        return await conn.QueryAsync<Profile>("SELECT * FROM profiles ORDER BY id ASC");
    }

    public async Task<Profile?> GetByIdAsync(long id)
    {
        using var conn = _db.CreateConnection();
        return await conn.QueryFirstOrDefaultAsync<Profile>(
            "SELECT * FROM profiles WHERE id = @id", new { id }
        );
    }
}
