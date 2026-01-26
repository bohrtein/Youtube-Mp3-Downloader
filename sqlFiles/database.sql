DROP DATABASE IF EXISTS musicDatabase;
CREATE DATABASE musicDatabase;
USE musicDatabase;

-- 2. Create Artists Table
CREATE TABLE artists (
    artist_id INT AUTO_INCREMENT PRIMARY KEY,
    artist_name VARCHAR(100) NOT NULL UNIQUE,
    bio TEXT
);

-- 3. Create Albums Table
CREATE TABLE albums (
    album_id INT AUTO_INCREMENT PRIMARY KEY,
    album_name VARCHAR(150) NOT NULL,
    release_date INT,
    artist_id INT,
    FOREIGN KEY (artist_id) REFERENCES artists(artist_id) ON DELETE CASCADE,
    cover_data MEDIUMBLOB,
    UNIQUE (album_name, artist_id)
);

-- 4. Create Songs Table
CREATE TABLE songs (
    song_id INT AUTO_INCREMENT PRIMARY KEY,
    song_title VARCHAR(150) NOT NULL,
    duration_seconds INT,
    track_number INT,
    album_id INT,
    release_date INT, -- Data column kept, reference removed
    bit_rate VARCHAR(10),
    file_type VARCHAR(10),
    source_url VARCHAR(30),
    FOREIGN KEY (album_id) REFERENCES albums(album_id) ON DELETE CASCADE,
    UNIQUE (song_title, album_id)
);

-- Prevent duplicate artist names
ALTER TABLE artists ADD UNIQUE (artist_name);

-- Prevent duplicate albums for the same artist 
-- (Allows two different artists to have an album with the same name, but not the same artist)
ALTER TABLE albums ADD UNIQUE (album_name, artist_id);

-- Prevent duplicate songs in the same album
ALTER TABLE songs ADD UNIQUE (song_title, album_id);

USE musicDatabase;

CREATE OR REPLACE VIEW album_gallery AS
SELECT 
    alb.album_id,
    alb.album_name,
    art.artist_name,
    alb.release_date
FROM albums alb
JOIN artists art ON alb.artist_id = art.artist_id
ORDER BY alb.release_date DESC;

    
																																						 
    
    




