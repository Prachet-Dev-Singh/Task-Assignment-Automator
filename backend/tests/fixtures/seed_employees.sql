-- seed_employees.sql — 10 employees for development and testing.
--
-- Skill vocabulary used here defines the canonical tags for the whole system.
-- All tags are lowercase. The extractor will be shown this vocabulary and must
-- choose from it for required_skills. Unknown skills go into unmapped_skills.
--
-- Canonical skill tags:
--   sql, python, powerbi, data-analysis, devops, react, java,
--   machine-learning, testing, infrastructure, security, reporting,
--   software-development
--
-- Distribution: 2 junior, 4 mid, 3 senior, 1 lead
-- Some employees are OOO (is_available=false) for constraint testing.

INSERT INTO employees (id, name, email, role, seniority, skills, capacity, is_available) VALUES
  (
    gen_random_uuid(),
    'Arjun Mehta',
    'arjun@company.com',
    'Junior Developer',
    'junior',
    ARRAY['python', 'testing', 'sql'],
    2,
    true
  ),
  (
    gen_random_uuid(),
    'Priya Kapoor',
    'priya@company.com',
    'Junior Data Analyst',
    'junior',
    ARRAY['sql', 'data-analysis', 'reporting'],
    2,
    false  -- OOO: used in constraint tests
  ),
  (
    gen_random_uuid(),
    'Rohan Sharma',
    'rohan@company.com',
    'Mid Software Developer',
    'mid',
    ARRAY['python', 'react', 'java', 'testing', 'software-development'],
    3,
    true
  ),
  (
    gen_random_uuid(),
    'Sneha Iyer',
    'sneha@company.com',
    'Mid Data Analyst',
    'mid',
    ARRAY['sql', 'powerbi', 'data-analysis', 'reporting'],
    3,
    true
  ),
  (
    gen_random_uuid(),
    'Vikram Nair',
    'vikram@company.com',
    'Mid DevOps Engineer',
    'mid',
    ARRAY['devops', 'python', 'infrastructure', 'security'],
    3,
    true
  ),
  (
    gen_random_uuid(),
    'Ananya Das',
    'ananya@company.com',
    'Mid Software Developer',
    'mid',
    ARRAY['react', 'java', 'python', 'software-development', 'testing'],
    3,
    true
  ),
  (
    gen_random_uuid(),
    'Kiran Rao',
    'kiran@company.com',
    'Senior Data Scientist',
    'senior',
    ARRAY['python', 'sql', 'machine-learning', 'data-analysis', 'reporting'],
    4,
    true
  ),
  (
    gen_random_uuid(),
    'Meera Pillai',
    'meera@company.com',
    'Senior Software Developer',
    'senior',
    ARRAY['java', 'react', 'python', 'software-development', 'testing', 'sql'],
    4,
    true
  ),
  (
    gen_random_uuid(),
    'Suresh Kumar',
    'suresh@company.com',
    'Senior DevOps Engineer',
    'senior',
    ARRAY['devops', 'infrastructure', 'security', 'python'],
    4,
    false  -- OOO: used in constraint tests
  ),
  (
    gen_random_uuid(),
    'Divya Singh',
    'divya@company.com',
    'Tech Lead',
    'lead',
    ARRAY['python', 'java', 'react', 'sql', 'machine-learning', 'devops', 'infrastructure', 'software-development'],
    5,
    true
  );

